# market-watch

[English](README.md) | [中文](README_zh.md)

**Real-time market monitoring and alert system for OpenClaw agents.**

Watch crypto prices (BTC, ETH, SOL, HYPE, XAUT, and more) and Chinese A-shares via HTTP polling. Monitor breaking news from Jin10, Wallstreetcn, CoinDesk, CoinTelegraph, The Block, and Decrypt with keyword matching. When a price condition is met or a keyword-matched news item appears, the agent gets notified and proactively contacts the user.

> Built as an [OpenClaw](https://github.com/openclaw) AgentSkill. Works out of the box with any OpenClaw agent.

---

## What It Does

| Feature | Status |
|---------|--------|
| **Price alerts** — HTTP polling from Binance, Hyperliquid, OKX, Bitget, CoinGecko | ✅ |
| **A-share alerts** — pytdx TCP polling (4s interval during market hours) | ✅ |
| **News alerts** — Jin10, Wallstreetcn, CoinDesk, CoinTelegraph, The Block, Decrypt | ✅ |
| **Daemon management** — background processes with auto-restart via launchd watchdog | ✅ |

---

## Quick Start

### 1. Install Python dependency

```bash
pip3 install requests pytdx
```

### 2. Register a price alert

```bash
SKILL="$HOME/.openclaw/skills/market-watch/scripts"

python3 "$SKILL/register-price-alert.py" \
  --agent your-agent-id \
  --asset ETH \
  --market crypto \
  --condition ">=" \
  --target 2150 \
  --context-summary "ETH exit window: sell 3.5 ETH, buy HYPE" \
  --session-key "agent:your-agent:feishu:direct:ou_xxx" \
  --reply-channel feishu \
  --reply-to "user:ou_xxx"
```

### 3. Register a news alert

```bash
python3 "$SKILL/register-news-alert.py" \
  --agent your-agent-id \
  --keywords "BTC ETF,BlackRock,Bitcoin" \
  --keyword-mode any \
  --sources "coindesk,cointelegraph,jin10" \
  --context-summary "Watch for ETF approval news" \
  --session-key "agent:your-agent:feishu:direct:ou_xxx" \
  --reply-channel feishu \
  --reply-to "user:ou_xxx"
```

> Both scripts automatically start the daemon after registering an alert.

### 4. Manage the daemon manually

```bash
DAEMON="$HOME/.openclaw/skills/market-watch/scripts/daemon.sh"

bash "$DAEMON" start   --agent your-agent-id   # start as needed (checks alert types)
bash "$DAEMON" stop    --agent your-agent-id   # stop both monitors
bash "$DAEMON" status  --agent your-agent-id   # status of both monitors
bash "$DAEMON" log     --agent your-agent-id   # logs from both monitors
```

### 5. Cancel alerts

```bash
SCRIPT="$HOME/.openclaw/skills/market-watch/scripts/cancel-alert.py"

python3 "$SCRIPT" --agent your-agent-id --list             # list active alerts
python3 "$SCRIPT" --agent your-agent-id --id eth-1741234   # cancel by ID
python3 "$SCRIPT" --agent your-agent-id --asset ETH        # cancel all ETH alerts
python3 "$SCRIPT" --agent your-agent-id --type price       # cancel all price alerts
python3 "$SCRIPT" --agent your-agent-id --type news        # cancel all news alerts
python3 "$SCRIPT" --agent your-agent-id --all              # cancel everything
```

### 6. (macOS) Install launchd watchdog

Automatically resurrects the daemon every 5 minutes if it crashed:

```bash
bash "$HOME/.openclaw/skills/market-watch/scripts/install-watchdog.sh" install --agent your-agent-id
```

---

## Data Sources

### Price Sources

| Exchange | Protocol | Assets | Latency |
|----------|----------|--------|---------|
| Binance | HTTP ticker (polling 5s) | BTC, ETH, SOL, BNB | ~100ms |
| Hyperliquid | HTTP allMids (polling 5s) | HYPE + all HL-listed assets | ~100ms |
| OKX | HTTP ticker (polling 5s) | BTC, ETH, SOL, XAUT, HYPE | ~100ms |
| Bitget | HTTP ticker (polling 5s) | BTC, ETH, SOL, HYPE | ~100ms |
| CoinGecko | HTTP polling (30s fallback) | Universal fallback | ~30s |
| pytdx | TCP request-response | A-shares (Shanghai/Shenzhen) | ~200ms |

**Asset priority (best-to-fallback):**
- BTC / ETH / SOL: Binance → Hyperliquid → OKX → Bitget → CoinGecko
- HYPE: Hyperliquid → OKX → Bitget → CoinGecko (no HYPEUSDT on Binance)
- XAUT: OKX → CoinGecko
- A-shares (e.g. `600519`): pytdx only (market hours: Mon–Fri 9:30–11:30 / 13:00–15:00 CST)

### News Sources

| Source | Type | Notes |
|--------|------|-------|
| Jin10 (金十数据) | HTTP polling | Unofficial API ⚠️ format may change |
| Wallstreetcn (华尔街见闻) | HTTP polling | Unofficial API ⚠️ format may change |
| CoinDesk | RSS feed | `https://www.coindesk.com/arc/outboundfeeds/rss/` |
| CoinTelegraph | RSS feed | `https://cointelegraph.com/rss` |
| The Block | RSS feed | `https://www.theblock.co/rss.xml` |
| Decrypt | RSS feed | `https://decrypt.co/feed` |

> ⚠️ **Jin10 and Wallstreetcn are unofficial interfaces.** They may add anti-scraping measures or change their response format at any time. The code handles graceful degradation — if either fails, other sources continue working.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     AI Agent (OpenClaw)                     │
│  register-price-alert.py / register-news-alert.py          │
└──────────────────────────┬──────────────────────────────────┘
                           │ writes alert to JSON
                           ▼
┌─────────────────────────────────────────────────────────────┐
│           market-alerts.json (shared state)                 │
│  ~/.openclaw/agents/{agent}/private/                        │
└──────┬───────────────────────────────────────┬──────────────┘
       │ read every 5s                          │ read every 5min
       ▼                                        ▼
┌───────────────────────┐         ┌─────────────────────────────┐
│  price-monitor.py     │         │  news-monitor.py             │
│  (daemon)             │         │  (daemon)                    │
│                       │         │                              │
│  HTTP polling (5s):   │         │  HTTP polling (5min):        │
│  Binance → HL → OKX   │         │  Jin10 / Wallstreetcn        │
│  → Bitget → CoinGecko │         │  CoinDesk / CoinTelegraph    │
│                       │         │  The Block / Decrypt         │
│  A-share (4s):        │         │                              │
│  pytdx TCP            │         │  Keyword matching (any/all)  │
│                       │         │  Dedup via hash window       │
└──────────┬────────────┘         └──────────────┬──────────────┘
           │                                     │
           └──────────────┬──────────────────────┘
                          │ openclaw agent --deliver
                          ▼
┌─────────────────────────────────────────────────────────────┐
│               Agent session receives:                       │
│  [MARKET_ALERT 触发] / [NEWS_ALERT 触发]                   │
│  • triggered condition / matched keywords                   │
│  • context_summary from registration time                   │
│  • transcript_file path for full context replay             │
└─────────────────────────────────────────────────────────────┘
```

**Key design choices:**

- **HTTP polling not WebSocket** — simpler reconnect logic, no session state
- **Shared JSON file** — zero IPC complexity; agent and daemon communicate via the filesystem
- **Auto-exit when no active alerts** — each daemon is launched on demand, not always-on
- **Price alerts: one-shot by default** — fires once, marks as `triggered`
- **News alerts: continuous by default** — keeps monitoring until cancelled or `--one-shot` set
- **Context replay** — alert carries `transcript_file` + `transcript_msg_id` so agent can reconstruct exactly what the user wanted

---

## File Structure

```
market-watch/
├── SKILL.md                        # OpenClaw agent instructions (loaded by agent runtime)
├── README.md                       # This file
├── README_zh.md                    # Chinese README
├── scripts/
│   ├── register-price-alert.py    # Register a new price alert + auto-start daemon
│   ├── register-news-alert.py     # Register a new news keyword alert + auto-start daemon
│   ├── cancel-alert.py            # List / cancel active alerts (supports --type news)
│   ├── price-monitor.py           # Background daemon — fetches prices, checks conditions
│   ├── news-monitor.py            # Background daemon — fetches news, keyword matching
│   ├── daemon.sh                  # Process lifecycle: start/stop/restart/status/log/ensure
│   └── install-watchdog.sh        # macOS launchd watchdog (auto-restart on crash)
└── references/
    └── exchange-api.md            # HTTP API reference for all exchanges and news sources
```

---

## Alert Data Format

Alerts are stored in `~/.openclaw/agents/{agent}/private/market-alerts.json`:

### Price Alert
```json
{
  "id":                "eth-1741234567",
  "type":              "price",
  "status":            "active",
  "asset":             "ETH",
  "market":            "crypto",
  "condition":         ">=",
  "target_price":      2150,
  "one_shot":          true,
  "context_summary":   "ETH exit window: sell 3.5 ETH, buy HYPE",
  "session_key":       "agent:your-agent:feishu:direct:ou_xxx",
  "agent_id":          "your-agent",
  "reply_channel":     "feishu",
  "reply_to":          "user:ou_xxx",
  "transcript_file":   "~/.openclaw/agents/{agent}/sessions/{session-id}.jsonl",
  "transcript_msg_id": "msg-id",
  "created_at":        "2026-03-12T13:00:00"
}
```

### News Alert
```json
{
  "id":                "news-1741234567",
  "type":              "news",
  "status":            "active",
  "keywords":          ["BTC ETF", "BlackRock", "Bitcoin"],
  "keyword_mode":      "any",
  "sources":           ["coindesk", "cointelegraph", "jin10"],
  "poll_interval":     300,
  "one_shot":          false,
  "context_summary":   "Watch for ETF approval news",
  "session_key":       "agent:your-agent:feishu:direct:ou_xxx",
  "agent_id":          "your-agent",
  "reply_channel":     "feishu",
  "reply_to":          "user:ou_xxx",
  "created_at":        "2026-03-12T13:00:00"
}
```

**`status` lifecycle:** `active` → `triggered` (condition/keyword met) | `cancelled` (manual)

---

## Runtime Files

| File | Path | Description |
|------|------|-------------|
| Alerts DB | `~/.openclaw/agents/{agent}/private/market-alerts.json` | Shared alert state |
| News state | `~/.openclaw/agents/{agent}/private/news-monitor-state.json` | Dedup hash windows |
| Price PID | `/tmp/market-watch-{agent}-price.pid` | price-monitor process ID |
| News PID | `/tmp/market-watch-{agent}-news.pid` | news-monitor process ID |
| Price log | `/tmp/market-watch-{agent}.log` | Rotating log (max 512KB × 3) |
| News log | `/tmp/market-watch-{agent}-news.log` | Rotating log (max 512KB × 4) |
| Watchdog plist | `~/Library/LaunchAgents/com.openclaw.market-watch.{agent}.plist` | macOS launchd config |

---

## For AI Agents (OpenClaw)

This skill ships with a `SKILL.md` that is automatically loaded by the OpenClaw agent runtime. You don't need to read this README at runtime.

**When to activate this skill:**
- User asks to "watch BTC", "alert me when ETH hits X", "盯盘", "set a price alert"
- User asks to monitor news: "帮我盯 ETF 相关新闻", "watch for BlackRock news"
- User asks to cancel or list current alerts
- You receive a `[MARKET_ALERT 触发]` or `[NEWS_ALERT 触发]` message

**Non-standard assets (e.g. PEPE, new listings):**
- Add the asset to `ASSET_EXCHANGES` in `price-monitor.py`
- Add its symbol mapping to the relevant exchange fetcher
- Restart the daemon: `bash daemon.sh restart --agent {agent}`

---

## Requirements

- Python 3.10+
- `requests` (`pip3 install requests`)
- `pytdx` (`pip3 install pytdx`) — A-share real-time quotes
- [OpenClaw](https://github.com/openclaw) agent runtime (for `openclaw agent --deliver`)
- macOS or Linux (launchd watchdog is macOS-only; Linux users can use `cron` instead)

---

## License

MIT
