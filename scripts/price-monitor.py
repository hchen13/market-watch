#!/usr/bin/env python3
"""
price-monitor.py — 价格盯盘守护进程

架构:
  - Crypto: 5s HTTP 轮询，交易所优先级 fallback
    Binance > Hyperliquid > OKX > Bitget > CoinGecko
  - A股: pytdx TCP 轮询（盘中 4s）

用法:
  python3 price-monitor.py --agent laok
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# 公共工具（get_session_uuid / deliver_message / atomic_write_json）
sys.path.insert(0, str(Path(__file__).parent))
from common import deliver_message, atomic_write_json  # noqa: E402

try:
    import requests
except ImportError:
    print("需要 requests: pip3 install requests")
    exit(1)

# ── Logging ───────────────────────────────────────────────────────────────────

from logging.handlers import RotatingFileHandler

log = logging.getLogger("price-monitor")
log.setLevel(logging.INFO)
_formatter = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S")

# ── 全局配置 ──────────────────────────────────────────────────────────────────

CRYPTO_POLL_INTERVAL = 5    # 秒
ASTOCK_POLL_INTERVAL = 4    # 秒（盘中）
HTTP_TIMEOUT = 5            # 秒
FAILURE_ALERT_SEC = 600     # 连续失败10分钟告警
PRICE_STALE_SEC = 60        # 超过此秒数的价格视为 stale，跳过触发检查

# 交易所优先级（全局）
EXCHANGE_PRIORITY = ["binance", "hyperliquid", "okx", "bitget", "coingecko"]

# 每个资产在哪些交易所有（按全局优先级筛选）
ASSET_EXCHANGES = {
    "BTC":  ["binance", "hyperliquid", "okx", "bitget", "coingecko"],
    "ETH":  ["binance", "hyperliquid", "okx", "bitget", "coingecko"],
    "SOL":  ["binance", "hyperliquid", "okx", "bitget", "coingecko"],
    "BNB":  ["binance", "okx", "coingecko"],
    # HYPE: Binance 上不存在 HYPEUSDT 交易对，从 binance 移除
    "HYPE": ["hyperliquid", "okx", "bitget", "coingecko"],
    "XAUT": ["okx", "coingecko"],
}

# ── Binance ───────────────────────────────────────────────────────────────────
# GET /api/v3/ticker/price?symbols=["BTCUSDT","ETHUSDT"]

BINANCE_SYMBOL_MAP = {
    "BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT",
    "BNB": "BNBUSDT",
    # HYPE: 已验证 HYPEUSDT 在 Binance 不存在（返回 -1121 Invalid symbol）
}
BINANCE_REVERSE = {v: k for k, v in BINANCE_SYMBOL_MAP.items()}


def fetch_binance(assets: list[str]) -> dict[str, float]:
    symbols = [BINANCE_SYMBOL_MAP[a] for a in assets if a in BINANCE_SYMBOL_MAP]
    if not symbols:
        return {}

    # 先尝试批量请求
    try:
        params = {"symbols": json.dumps(symbols)}
        resp = requests.get(
            "https://api.binance.com/api/v3/ticker/price",
            params=params, timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        result = {}
        for item in resp.json():
            asset = BINANCE_REVERSE.get(item["symbol"])
            if asset and float(item["price"]) > 0:
                result[asset] = float(item["price"])
        return result
    except Exception as e:
        log.debug(f"Binance 批量请求失败 ({e})，降级逐 symbol 请求")

    # 批量失败 → 逐 symbol 回退（S-05：隔离单个无效 symbol 的影响）
    result = {}
    for sym in symbols:
        try:
            resp = requests.get(
                f"https://api.binance.com/api/v3/ticker/price?symbol={sym}",
                timeout=HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            asset = BINANCE_REVERSE.get(data.get("symbol", ""))
            price = float(data.get("price", 0))
            if asset and price > 0:
                result[asset] = price
        except Exception:
            continue
    return result


# ── Hyperliquid ───────────────────────────────────────────────────────────────
# POST https://api.hyperliquid.xyz/info  {"type": "allMids"}

HL_ASSET_MAP = {
    "BTC": "BTC", "ETH": "ETH", "SOL": "SOL", "HYPE": "HYPE",
    "BNB": "BNB", "XAUT": "XAUT",
}


def fetch_hyperliquid(assets: list[str]) -> dict[str, float]:
    resp = requests.post(
        "https://api.hyperliquid.xyz/info",
        json={"type": "allMids"}, timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    mids = resp.json()  # {"BTC": "69500.5", "ETH": "2025.3", ...}
    result = {}
    for asset in assets:
        hl_name = HL_ASSET_MAP.get(asset, asset)
        if hl_name in mids:
            try:
                price = float(mids[hl_name])
                if price > 0:
                    result[asset] = price
            except (ValueError, TypeError):
                pass
    return result


# ── OKX ───────────────────────────────────────────────────────────────────────
# GET /api/v5/market/ticker?instId=BTC-USDT

OKX_INST_MAP = {
    "BTC": "BTC-USDT", "ETH": "ETH-USDT", "SOL": "SOL-USDT",
    "BNB": "BNB-USDT", "HYPE": "HYPE-USDT", "XAUT": "XAUT-USDT",
}


def fetch_okx(assets: list[str]) -> dict[str, float]:
    result = {}
    for asset in assets:
        inst = OKX_INST_MAP.get(asset)
        if not inst:
            continue
        try:
            resp = requests.get(
                f"https://www.okx.com/api/v5/market/ticker?instId={inst}",
                timeout=HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if data:
                price = float(data[0].get("last", 0))
                if price > 0:
                    result[asset] = price
        except Exception:
            continue
    return result


# ── Bitget ────────────────────────────────────────────────────────────────────
# GET /api/v2/spot/market/tickers?symbol=BTCUSDT

BITGET_SYMBOL_MAP = {
    "BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "HYPE": "HYPEUSDT",
}


def fetch_bitget(assets: list[str]) -> dict[str, float]:
    result = {}
    for asset in assets:
        sym = BITGET_SYMBOL_MAP.get(asset)
        if not sym:
            continue
        try:
            resp = requests.get(
                f"https://api.bitget.com/api/v2/spot/market/tickers?symbol={sym}",
                timeout=HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if data:
                price = float(data[0].get("lastPr", 0))
                if price > 0:
                    result[asset] = price
        except Exception:
            continue
    return result


# ── CoinGecko ─────────────────────────────────────────────────────────────────
# GET /api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd

COINGECKO_MAP = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
    "BNB": "binancecoin", "HYPE": "hyperliquid", "XAUT": "tether-gold",
}
COINGECKO_REVERSE = {v: k for k, v in COINGECKO_MAP.items()}


def fetch_coingecko(assets: list[str]) -> dict[str, float]:
    ids = [COINGECKO_MAP[a] for a in assets if a in COINGECKO_MAP]
    if not ids:
        return {}
    resp = requests.get(
        f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(ids)}&vs_currencies=usd",
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    result = {}
    for cg_id, vals in data.items():
        asset = COINGECKO_REVERSE.get(cg_id)
        if asset and vals.get("usd", 0) > 0:
            result[asset] = float(vals["usd"])
    return result


# ── 统一取价 ──────────────────────────────────────────────────────────────────

EXCHANGE_FETCHERS = {
    "binance":      fetch_binance,
    "hyperliquid":  fetch_hyperliquid,
    "okx":          fetch_okx,
    "bitget":       fetch_bitget,
    "coingecko":    fetch_coingecko,
}


def fetch_all_crypto(needed: set[str]) -> dict[str, tuple[float, str, float]]:
    """
    按优先级从交易所获取价格。
    返回 {asset: (price, source, timestamp)}。
    timestamp 为本次 fetch 开始时的 Unix 时间，用于 stale 价格检查（F-01）。
    """
    results: dict[str, tuple[float, str, float]] = {}
    remaining = set(needed)
    fetch_ts = time.time()  # 本次 fetch 的统一时间戳

    for exchange in EXCHANGE_PRIORITY:
        if not remaining:
            break
        fetchable = [a for a in remaining if exchange in ASSET_EXCHANGES.get(a, [])]
        if not fetchable:
            continue
        fetcher = EXCHANGE_FETCHERS.get(exchange)
        if not fetcher:
            continue
        try:
            prices = fetcher(fetchable)
            for asset, price in prices.items():
                results[asset] = (price, exchange, fetch_ts)
                remaining.discard(asset)
        except Exception as e:
            log.debug(f"{exchange} 失败: {e}")
            continue

    return results


# ── A股 pytdx ─────────────────────────────────────────────────────────────────

ASTOCK_SERVERS = [
    ("115.238.90.165", 7709), ("115.238.56.198", 7709),
    ("180.153.18.170", 7709), ("101.227.73.20",  7709),
]


def is_astock_trading_hours() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    hm = now.hour * 100 + now.minute
    return (930 <= hm <= 1130) or (1300 <= hm <= 1500)


def fetch_astock(codes: list[str]) -> dict[str, float]:
    if not codes or not is_astock_trading_hours():
        return {}
    try:
        from pytdx.hq import TdxHq_API
    except ImportError:
        return {}

    stocks = []
    for code in codes:
        market = 1 if code.startswith(("6", "5")) else 0
        stocks.append((market, code))

    for ip, port in ASTOCK_SERVERS:
        try:
            api = TdxHq_API()
            with api.connect(ip, port):
                data = api.get_security_quotes(stocks)
                if data:
                    return {item["code"]: float(item["price"])
                            for item in data if item.get("price")}
        except Exception:
            continue
    return {}


# ── 通知 ──────────────────────────────────────────────────────────────────────

def fire_alert(alert: dict, price: float, source: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    msg = (
        f"[MARKET_ALERT 触发 · 请处理后联系用户]\n\n"
        f"信号：{alert['asset']} 当前 ${price:,.4g}，"
        f"已触达设定条件（{alert['condition']} ${alert['target_price']:,}）\n"
        f"数据来源：{source}\n"
        f"触发时间：{ts}\n\n"
        f"背景（设盘时记录）：\n{alert.get('context_summary', '（未记录）')}\n\n"
        f"完整上下文：\n"
        f"  文件：{alert.get('transcript_file', '未记录')}\n"
        f"  消息ID：{alert.get('transcript_msg_id', '未记录')}\n\n"
        f"你的任务：\n"
        f"1. 阅读背景，必要时读取 transcript 文件还原上下文\n"
        f"2. 以自己的口吻主动告知用户：价格条件已触达\n"
        f"3. 结合当前市场给出简要判断，询问用户是否执行操作"
    )

    log.info(f"🔔 ALERT: {alert['asset']} @ ${price:.4g} [{source}]")
    deliver_message(alert, msg)


def notify_failure(agent_id: str, alerts_file: Path, minutes: int) -> None:
    """
    连续取价失败超过阈值，通知 agent。
    M-01: 使用与 fire_alert 相同的 deliver_message 通知路径，
    路由信息从活跃警报中读取（取第一条），如无则 fallback 到 agent 默认。
    """
    msg = (
        f"[MARKET_ALERT · 系统异常]\n\n"
        f"价格监控已连续 {minutes} 分钟无法获取任何加密货币价格。\n"
        f"可能原因：网络代理故障 / 所有交易所API不可达。\n\n"
        f"你的任务：\n"
        f"1. 告知用户盯盘程序取价异常\n"
        f"2. 检查网络和代理状态\n"
        f"3. 尝试手动验证: curl https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
    )

    # 尝试从活跃警报中读取路由信息（M-01：与 fire_alert 路径一致）
    route_alert: dict = {"agent_id": agent_id}
    try:
        if alerts_file.exists():
            data = json.loads(alerts_file.read_text())
            active = [a for a in data.get("alerts", []) if a.get("status") == "active"]
            if active:
                route_alert = active[0]
    except Exception:
        pass

    deliver_message(route_alert, msg)


# ── 主循环 ────────────────────────────────────────────────────────────────────

MAX_LOG_BYTES = 512 * 1024    # 单个日志文件上限 512KB
LOG_BACKUP_COUNT = 2          # 保留2个轮转备份，总上限 ~1.5MB
ALERTS_RETAIN_DAYS = 7        # 已完成警报保留天数
ALERTS_CLEANUP_INTERVAL = 3600  # 每小时清理一次


def _setup_logging(agent_id: str):
    log_file = Path(f"/tmp/market-watch-{agent_id}.log")
    handler = RotatingFileHandler(
        str(log_file), maxBytes=MAX_LOG_BYTES, backupCount=LOG_BACKUP_COUNT,
    )
    handler.setFormatter(_formatter)
    log.addHandler(handler)
    # 同时输出到 stderr（daemon.sh 的 nohup 会重定向）
    console = logging.StreamHandler()
    console.setFormatter(_formatter)
    log.addHandler(console)


def _cleanup_old_alerts(alerts_file: Path):
    """清理超过保留天数的已触发/已取消警报"""
    if not alerts_file.exists():
        return
    try:
        with open(alerts_file) as f:
            data = json.load(f)
        alerts = data.get("alerts", [])
        cutoff = time.time() - ALERTS_RETAIN_DAYS * 86400
        kept = []
        removed = 0
        for a in alerts:
            if a.get("status") in ("triggered", "cancelled"):
                ts_str = a.get("triggered_at") or a.get("created_at", "")
                try:
                    ts = datetime.fromisoformat(ts_str).timestamp()
                    if ts < cutoff:
                        removed += 1
                        continue
                except (ValueError, TypeError):
                    pass
            kept.append(a)
        if removed:
            data["alerts"] = kept
            atomic_write_json(alerts_file, data)
            log.info(f"清理 {removed} 条过期警报记录（>{ALERTS_RETAIN_DAYS}天）")
    except Exception:
        pass


def run(agent_id: str, alerts_file: Path):
    _setup_logging(agent_id)
    log.info(f"=== price-monitor start | agent={agent_id} | interval={CRYPTO_POLL_INTERVAL}s ===")

    # F-01: prices 字典加时间戳，格式 {asset: (price, source, timestamp)}
    prices: dict[str, tuple[float, str, float]] = {}
    last_astock = 0.0
    last_log = 0.0
    last_cleanup = 0.0
    consecutive_fail_since: Optional[float] = None
    failure_notified = False

    while True:
        cycle_start = time.time()

        # ── 读取活跃警报 ──
        try:
            if alerts_file.exists():
                with open(alerts_file) as f:
                    data = json.load(f)
            else:
                data = {"alerts": []}
        except Exception:
            data = {"alerts": []}

        alerts = data.get("alerts", [])
        active = [a for a in alerts if a.get("status") == "active"
                  and a.get("type", "price") == "price"]

        # 无活跃警报 → 自动退出
        all_active = [a for a in alerts if a.get("status") == "active"]
        if not all_active:
            log.info("无活跃警报，守护进程自动退出")
            # S-01: 使用新格式 PID 文件（与 daemon.sh 一致）
            pid_file = Path(f"/tmp/market-watch-{agent_id}-price.pid")
            pid_file.unlink(missing_ok=True)
            return

        # ── 收集需要的资产 ──
        crypto_needed: set[str] = set()
        astock_needed: list[str] = []
        for a in active:
            asset = a["asset"].upper()
            market = a.get("market", "crypto")
            if market == "astock":
                if asset not in astock_needed:
                    astock_needed.append(asset)
            else:
                crypto_needed.add(asset)

        # ── 取价：Crypto ──
        if crypto_needed:
            fetched = fetch_all_crypto(crypto_needed)
            if fetched:
                prices.update(fetched)
                consecutive_fail_since = None
                failure_notified = False
            else:
                # 全部交易所失败
                if consecutive_fail_since is None:
                    consecutive_fail_since = time.time()
                elapsed = time.time() - consecutive_fail_since
                if elapsed >= FAILURE_ALERT_SEC and not failure_notified:
                    notify_failure(agent_id, alerts_file, int(elapsed / 60))
                    failure_notified = True

        # ── 取价：A股 ──
        now = time.time()
        if astock_needed and now - last_astock >= ASTOCK_POLL_INTERVAL:
            last_astock = now
            astock_prices = fetch_astock(astock_needed)
            for code, price in astock_prices.items():
                # F-01: A股价格也加时间戳
                prices[code] = (price, "pytdx", time.time())

        # ── 定期清理过期警报 ──
        if now - last_cleanup >= ALERTS_CLEANUP_INTERVAL:
            last_cleanup = now
            _cleanup_old_alerts(alerts_file)

        # ── 定期日志 ──
        if now - last_log >= 60:
            last_log = now
            snap = " | ".join(
                f"{a}=${p[0]:,.4g}[{p[1]}] age={int(now-p[2])}s"
                for a, p in sorted(prices.items())
            )
            log.info(f"Prices: {snap or '(无数据)'}")
            log.info(f"Active: {len(active)} alerts")

        # ── 检查警报 ──
        modified = False
        for alert in active:
            asset = alert["asset"].upper()
            market = alert.get("market", "crypto")

            if market == "astock" and not is_astock_trading_hours():
                continue

            price_info = prices.get(asset)
            if not price_info:
                continue

            current_price, source, price_ts = price_info

            # F-01: 价格时效校验 — stale 价格跳过触发，避免假警报
            age = time.time() - price_ts
            if age > PRICE_STALE_SEC:
                log.warning(
                    f"Stale price for {asset} ({int(age)}s old, limit={PRICE_STALE_SEC}s), "
                    f"skipping alert check"
                )
                continue

            target = float(alert["target_price"])
            condition = alert["condition"]
            triggered = {
                ">=": current_price >= target, "<=": current_price <= target,
                ">":  current_price > target,  "<":  current_price < target,
            }.get(condition, False)

            if triggered:
                fire_alert(alert, current_price, source)
                if alert.get("one_shot", True):
                    alert["status"] = "triggered"
                    alert["triggered_at"] = datetime.now().isoformat()
                    alert["triggered_price"] = current_price
                    alert["triggered_source"] = source
                    modified = True
                log.info(f"🔔 {asset} @ ${current_price:,.4g} [{source}] 触达 {condition} ${target:,}")

        if modified:
            data["alerts"] = alerts
            # S-02: 原子替换写入，防并发损坏
            atomic_write_json(alerts_file, data)

        # ── 等待下一轮 ──
        elapsed = time.time() - cycle_start
        sleep_time = max(0.5, CRYPTO_POLL_INTERVAL - elapsed)
        time.sleep(sleep_time)


# ── 入口 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Price Monitor")
    parser.add_argument("--agent", default="laok")
    parser.add_argument("--alerts-file", default="")
    args = parser.parse_args()

    default_alerts = Path.home() / f".openclaw/agents/{args.agent}/private/market-alerts.json"
    alerts_file = Path(args.alerts_file) if args.alerts_file else default_alerts
    alerts_file.parent.mkdir(parents=True, exist_ok=True)

    run(args.agent, alerts_file)
