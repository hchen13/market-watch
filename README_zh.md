# market-watch

[English](README.md) | **中文**

**给 OpenClaw agent 用的实时行情监控与警报系统。**

监控加密货币价格（BTC、ETH、SOL、HYPE、XAUT 等）和 A 股行情，当价格触达设定条件时，自动通知 agent，由 agent 主动联系用户。

> 这是一个 [OpenClaw](https://github.com/openclaw) AgentSkill，任何 OpenClaw agent 即插即用。

---

## 功能

| 功能 | 状态 |
|------|------|
| **价格警报** — HTTP 轮询 Binance / Hyperliquid / OKX / Bitget / CoinGecko | ✅ |
| **A 股警报** — pytdx TCP 轮询（盘中 4 秒间隔） | ✅ |
| **守护进程管理** — 后台运行，launchd 看门狗自动重启 | ✅ |
| **新闻警报** — RSS / API 关键词匹配 | 🚧 规划中 |

---

## 快速开始

### 1. 安装依赖

```bash
pip3 install requests pytdx
```

### 2. 注册价格警报

```bash
SKILL="$HOME/.openclaw/skills/market-watch/scripts"

python3 "$SKILL/register-price-alert.py" \
  --agent your-agent-id \
  --asset ETH \
  --market crypto \
  --condition ">=" \
  --target 2150 \
  --context-summary "ETH 减仓窗口：卖 3.5 枚 ETH 换 HYPE" \
  --session-key "agent:your-agent:feishu:direct:ou_xxx" \
  --reply-channel feishu \
  --reply-to "user:ou_xxx"
```

> 注册后自动拉起守护进程，无需手动启动。

### 3. 手动管理守护进程

```bash
DAEMON="$HOME/.openclaw/skills/market-watch/scripts/daemon.sh"

bash "$DAEMON" start   --agent your-agent-id   # 启动
bash "$DAEMON" stop    --agent your-agent-id   # 停止
bash "$DAEMON" status  --agent your-agent-id   # 查看状态
bash "$DAEMON" log     --agent your-agent-id   # 查看日志
```

### 4. 取消警报

```bash
SCRIPT="$HOME/.openclaw/skills/market-watch/scripts/cancel-alert.py"

python3 "$SCRIPT" --agent your-agent-id --list             # 列出活跃警报
python3 "$SCRIPT" --agent your-agent-id --id eth-1741234   # 按 ID 取消
python3 "$SCRIPT" --agent your-agent-id --asset ETH        # 取消所有 ETH 警报
python3 "$SCRIPT" --agent your-agent-id --all              # 取消全部
```

### 5.（macOS）安装看门狗

每 5 分钟检查一次，崩溃后自动重启守护进程：

```bash
bash "$HOME/.openclaw/skills/market-watch/scripts/install-watchdog.sh" install --agent your-agent-id
```

---

## 数据源

| 交易所 | 协议 | 支持资产 | 延迟 |
|--------|------|---------|------|
| Binance | HTTP ticker | BTC, ETH, SOL, BNB, HYPE | ~100ms |
| Hyperliquid | HTTP allMids | HYPE + 全部 HL 上线资产 | ~100ms |
| OKX | HTTP ticker | BTC, ETH, SOL, XAUT, HYPE | ~100ms |
| Bitget | HTTP ticker | BTC, ETH, SOL, HYPE | ~100ms |
| CoinGecko | HTTP 轮询（30s） | 兜底覆盖 | ~30s |
| pytdx | TCP 请求-响应 | A 股（沪深） | ~200ms |

**取价优先级（逐级降级）：**
- BTC / ETH / SOL：Binance → Hyperliquid → OKX → Bitget → CoinGecko
- HYPE：Hyperliquid → Binance → OKX → Bitget → CoinGecko
- XAUT：OKX → CoinGecko
- A 股（如 `601899`）：仅 pytdx（交易时段：周一至周五 9:30–11:30 / 13:00–15:00）

---

## 架构

```
┌─────────────────────────────────────────────────────┐
│                  AI Agent（OpenClaw）                │
│         调用 register-price-alert.py 注册警报       │
└───────────────────────────┬─────────────────────────┘
                            │ 写入 alert 到 JSON
                            ▼
┌─────────────────────────────────────────────────────┐
│         market-alerts.json（共享状态文件）            │
│    ~/.openclaw/agents/{agent}/private/               │
└───────────────────────────┬─────────────────────────┘
                            │ 每 5 秒读取
                            ▼
┌─────────────────────────────────────────────────────┐
│            price-monitor.py（守护进程）              │
│                                                     │
│  HTTP 轮询（5s）：                                   │
│    Binance → Hyperliquid → OKX → Bitget → CoinGecko │
│  A 股轮询（4s，盘中）：                              │
│    pytdx TCP → 备用服务器                            │
│                                                     │
│  条件触达时：                                        │
│    openclaw agent --deliver → 发送 MARKET_ALERT     │
└─────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────┐
│               Agent session 收到：                   │
│  [MARKET_ALERT 触发 · 请处理后联系用户]              │
│  • 当前价格 + 触达的条件                             │
│  • 注册时记录的 context_summary                      │
│  • transcript_file 路径用于完整上下文回溯            │
└─────────────────────────────────────────────────────┘
```

**关键设计决策：**

- **HTTP 轮询而非 WebSocket** — 省代理流量，重连逻辑简单，无状态
- **JSON 文件共享状态** — 零 IPC 复杂度，agent 和 daemon 通过文件系统通信
- **无活跃警报自动退出** — daemon 按需拉起，不常驻
- **默认一次性触发** — 触发后标记 `triggered`，停止监控
- **上下文回溯** — alert 携带 `transcript_file` + `transcript_msg_id`，agent 可精确还原用户意图

---

## 文件结构

```
market-watch/
├── SKILL.md                      # OpenClaw agent 指令（agent 运行时自动加载）
├── README.md                     # 英文说明
├── README_zh.md                  # 本文件
├── scripts/
│   ├── register-price-alert.py  # 注册价格警报 + 自动拉起 daemon
│   ├── cancel-alert.py          # 列出 / 取消活跃警报
│   ├── price-monitor.py         # 后台守护进程 — 取价、检查条件
│   ├── daemon.sh                # 进程生命周期管理：start / stop / restart / status / log
│   └── install-watchdog.sh      # macOS launchd 看门狗（崩溃自动重启）
└── references/
    └── exchange-api.md          # 各交易所 API 参考
```

---

## 警报数据格式

警报存储在 `~/.openclaw/agents/{agent}/private/market-alerts.json`：

```json
{
  "alerts": [
    {
      "id":                "eth-1741234567",
      "type":              "price",
      "status":            "active",
      "asset":             "ETH",
      "market":            "crypto",
      "condition":         ">=",
      "target_price":      2150,
      "one_shot":          true,
      "context_summary":   "ETH 减仓窗口：卖 3.5 枚 ETH 换 HYPE",
      "session_key":       "agent:your-agent:feishu:direct:ou_xxx",
      "agent_id":          "your-agent",
      "reply_channel":     "feishu",
      "reply_to":          "user:ou_xxx",
      "created_at":        "2026-03-12T13:00:00"
    }
  ]
}
```

**状态流转：** `active` → `triggered`（条件触达）| `cancelled`（手动取消）

---

## 给 AI Agent 的指引

本 skill 附带 `SKILL.md`，OpenClaw agent 运行时会自动加载。运行时不需要读这个 README，`SKILL.md` 是你的参考。

**什么时候激活：**
- 用户说"帮我盯 BTC"、"ETH 到 2150 通知我"、"set a price alert"
- 用户要取消或查看当前警报
- 你收到 `[MARKET_ALERT 触发]` 消息

**触发流程：**
1. 从对话中提取资产、条件、目标价、用户意图
2. 调用 `register-price-alert.py`，`--context-summary` 记录用户意图
3. 回复用户："设好了，[资产] [条件] [目标价] 到了通知你。"
4. 收到 `[MARKET_ALERT 触发]` 时：读 `context_summary`，必要时回溯 `transcript_file`，主动联系用户

**添加非标资产（如 PEPE、新上线币种）：**
- 在 `price-monitor.py` 的 `ASSET_EXCHANGES` 中添加资产
- 在对应交易所的 fetcher 函数中添加 symbol 映射
- 重启 daemon：`bash daemon.sh restart --agent {agent}`

---

## 运行时文件

| 文件 | 路径 | 说明 |
|------|------|------|
| 警报数据库 | `~/.openclaw/agents/{agent}/private/market-alerts.json` | 共享警报状态 |
| PID 文件 | `/tmp/market-watch-{agent}.pid` | 守护进程 PID |
| 日志文件 | `/tmp/market-watch-{agent}.log` | 轮转日志（上限 512KB × 3） |
| 看门狗配置 | `~/Library/LaunchAgents/com.openclaw.market-watch.{agent}.plist` | macOS launchd 配置 |

---

## 环境要求

- Python 3.10+
- `requests`（`pip3 install requests`）
- `pytdx`（`pip3 install pytdx`）— A 股实时行情
- [OpenClaw](https://github.com/openclaw) agent 运行时（提供 `openclaw agent --deliver`）
- macOS 或 Linux（launchd 看门狗仅 macOS；Linux 可用 cron 替代）

---

## License

MIT
