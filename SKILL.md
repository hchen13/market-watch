---
name: "market-watch"
description: "Market monitoring and alert system for prices and news. Use when the user asks to watch a price, monitor market conditions, get notified when an asset hits a target, or keep an eye on breaking news. Covers crypto (BTC/ETH/HYPE/SOL/XAUT etc.) and A-shares (real-time via TongDaXin)."
---

# Market Watch Skill

两类监控，共享同一套 alert 数据结构和通知回路：

| 类型 | 数据源 | 状态 |
|------|--------|------|
| **价格盯盘** | WebSocket（Binance/OKX/Bitget/Hyperliquid）+ pytdx（A股）+ CoinGecko fallback | ✅ 已实现 |
| **新闻盯盘** | RSS/API 关键词匹配 | 🚧 待实现（扩展点已预留） |

---

## 数据源和精度

| 来源 | 协议 | 资产 | 延迟 |
|------|------|------|------|
| Binance | WebSocket bookTicker | BTC/ETH/SOL/BNB/HYPE | 实时 |
| OKX | WebSocket tickers | BTC/ETH/SOL/XAUT/HYPE | 实时 |
| Bitget | WebSocket ticker | BTC/ETH/SOL/HYPE | 实时 |
| Hyperliquid | WebSocket allMids | HYPE 等所有 HL 资产 | 实时 |
| pytdx | TCP 轮询（盘中 4s） | A股（沪深） | ~200ms |
| CoinGecko | HTTP 轮询（30s） | 全资产 fallback | 30s |

**Asset → Exchange 优先级:**
- BTC/ETH/SOL: Binance → OKX → Bitget → CoinGecko
- HYPE: Hyperliquid → Bitget → OKX → CoinGecko
- XAUT: OKX → CoinGecko

---

## Alert 数据结构

所有警报存入 `~/.openclaw/agents/{agent}/private/market-alerts.json`。

**公共字段（所有类型）：**
```json
{
  "id":               "eth-1741234567",
  "type":             "price",           // "price" | "news"
  "status":           "active",          // active | triggered | cancelled
  "one_shot":         true,
  "context_summary":  "ETH减仓窗口：减3.5枚，套出换HYPE",
  "session_key":      "agent:laok:feishu:direct:ou_xxx",
  "agent_id":         "laok",
  "reply_channel":    "feishu",
  "reply_to":         "user:ou_xxx",
  "transcript_file":  "/path/to/session.jsonl",
  "transcript_msg_id": "msg-id",
  "created_at":       "2026-03-12T13:00:00"
}
```

**价格类额外字段：**
```json
{
  "asset":        "ETH",
  "market":       "crypto",    // "crypto" | "astock"
  "condition":    ">=",        // >= | <= | > | <
  "target_price": 2150
}
```

**新闻类字段（待实现，扩展点）：**
```json
{
  "sources":    ["coindesk-rss", "reuters-rss"],
  "keywords":   ["ceasefire", "停火", "Iran deal"],
  "match_mode": "any"          // "any" | "all"
}
```

---

## 价格盯盘工作流

### 1. 设置价格警报

```bash
SKILL="$HOME/.openclaw/skills/market-watch/scripts"

python3 "$SKILL/register-price-alert.py" \
  --agent laok \
  --asset ETH \
  --market crypto \
  --condition ">=" \
  --target 2150 \
  --context-summary "ETH减仓窗口：减3.5枚ETH（OKX），套出约\$7,500买HYPE" \
  --session-key "agent:laok:feishu:direct:ou_xxx" \
  --reply-channel feishu \
  --reply-to "user:ou_xxx"
```

**参数说明：**
- `--market`: `crypto`（加密）或 `astock`（A股，代码如 `600519`）
- `--condition`: `>=` / `<=` / `>` / `<`
- `--session-key`: 用户的当前 session key（稳定标识，用于触发时找到正确 session）
- `--reply-to`: 飞书通知目标，格式 `user:ou_xxx`

### 2. 启动守护进程

```bash
bash "$HOME/.openclaw/skills/market-watch/scripts/daemon.sh" start --agent laok
```

守护进程启动后：
- 自动连接 4 个交易所 WebSocket（Binance/OKX/Bitget/Hyperliquid）
- 启动 CoinGecko 30s fallback 轮询
- 如果有 A股警报，启动 pytdx 盘中轮询（4s）
- 每秒检查活跃警报，触达则通知

### 3. 查看和取消警报

```bash
python3 "$SKILL/cancel-alert.py" --agent laok --list            # 列出全部活跃警报
python3 "$SKILL/cancel-alert.py" --agent laok --id eth-1741234 # 按 ID 取消
python3 "$SKILL/cancel-alert.py" --agent laok --asset ETH       # 取消资产所有警报
python3 "$SKILL/cancel-alert.py" --agent laok --type price      # 取消所有价格警报
python3 "$SKILL/cancel-alert.py" --agent laok --all             # 取消全部
```

---

## 新闻盯盘（待实现）

新闻监控将由以下组件承接，预留扩展点：

- **`register-news-alert.py`** — 注册关键词/信源警报（待实现）
- **`news-monitor.py`** — RSS/API 扫描，关键词匹配（待实现）
- **`daemon.sh`** — 已支持扩展，统一进程管理

触发机制、通知回路与价格盯盘完全一致，共用 `market-alerts.json` 文件（通过 `type: "news"` 区分）。

---

## 守护进程管理

```bash
DAEMON="$HOME/.openclaw/skills/market-watch/scripts/daemon.sh"

bash "$DAEMON" start    # 启动（连接 WebSocket + 开始轮询）
bash "$DAEMON" stop     # 停止
bash "$DAEMON" restart  # 重启（重建所有 WS 连接）
bash "$DAEMON" status   # 状态 + 活跃警报列表
bash "$DAEMON" log      # 最近 40 行日志
bash "$DAEMON" log --lines 100  # 更多日志
```

**文件路径:**
- PID：`/tmp/market-watch-{agent}.pid`
- 日志：`/tmp/market-watch-{agent}.log`
- 警报：`~/.openclaw/agents/{agent}/private/market-alerts.json`

---

## 收到 `[MARKET_ALERT 触发]` 时

注入消息格式：`[MARKET_ALERT 触发 · 请处理后联系用户]`

处理步骤：
1. 读取 `context_summary`（设盘时的上下文核心）
2. 如需更多细节，读取 `transcript_file` 指定位置
3. **以自己的口吻主动告知用户**：条件已触达，当前价格是多少
4. 结合当前市场给出简要判断，询问是否执行操作

---

## 注意事项

- **新增非常规资产**（如 PEPE）：restart 守护进程，WS 连接不自动热更新
- **HYPE**: 优先用 Hyperliquid WS，allMids 包含 HYPE 现货 mid price
- **XAUT**: 仅 OKX 有，且 OKX WS 可能因地区限制连接失败，CoinGecko 兜底
- **A股**: 只在交易时段（9:30-11:30 / 13:00-15:00）轮询，非交易时段自动跳过
- **pytdx**: 纯 TCP 请求-响应协议，无推送能力，4s 轮询是合理下限
