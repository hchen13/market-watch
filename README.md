# market-watch

**Real-time market monitoring and alert system for OpenClaw agents.**

Watch crypto prices (BTC, ETH, SOL, HYPE, XAUT, and more) and Chinese A-shares via live WebSocket feeds and TCP polling. When a price condition is met, the agent gets notified and proactively contacts the user.

> Built as an [OpenClaw](https://github.com/openclaw) AgentSkill. Works out of the box with any OpenClaw agent.

---

## What It Does

| Feature | Status |
|---------|--------|
| **Price alerts** — WebSocket + HTTP polling from Binance, OKX, Bitget, Hyperliquid, CoinGecko | ✅ |
| **A-share alerts** — pytdx TCP polling (4s interval during market hours) | ✅ |
| **Daemon management** — background process with auto-restart via launchd watchdog | ✅ |
| **News alerts** — RSS/API keyword matching | 🚧 planned (extension point reserved) |

---

## Quick Start

### 1. Install Python dependency

```bash
pip3 install requests
# Optional: for A-share (China stocks) support
pip3 install pytdx
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

> The script automatically starts the daemon after registering an alert.

### 3. Manage the daemon manually

```bash
DAEMON="$HOME/.openclaw/skills/market-watch/scripts/daemon.sh"

bash "$DAEMON" start   --agent your-agent-id
bash "$DAEMON" stop    --agent your-agent-id
bash "$DAEMON" status  --agent your-agent-id
bash "$DAEMON" log     --agent your-agent-id
```

### 4. Cancel alerts

```bash
SCRIPT="$HOME/.openclaw/skills/market-watch/scripts/cancel-alert.py"

python3 "$SCRIPT" --agent your-agent-id --list             # list active
python3 "$SCRIPT" --agent your-agent-id --id eth-1741234   # cancel by ID
python3 "$SCRIPT" --agent your-agent-id --asset ETH        # cancel all ETH alerts
python3 "$SCRIPT" --agent your-agent-id --all              # cancel everything
```

### 5. (macOS) Install launchd watchdog

Automatically resurrects the daemon every 5 minutes if it crashed:

```bash
bash "$HOME/.openclaw/skills/market-watch/scripts/install-watchdog.sh" install --agent your-agent-id
```

---

## Data Sources

| Exchange | Protocol | Assets | Latency |
|----------|----------|--------|---------|
| Binance | HTTP ticker | BTC, ETH, SOL, BNB, HYPE | ~100ms |
| Hyperliquid | HTTP allMids | HYPE + all HL-listed assets | ~100ms |
| OKX | HTTP ticker | BTC, ETH, SOL, XAUT, HYPE | ~100ms |
| Bitget | HTTP ticker | BTC, ETH, SOL, HYPE | ~100ms |
| CoinGecko | HTTP polling (30s) | Universal fallback | ~30s |
| pytdx | TCP request-response | A-shares (Shanghai/Shenzhen) | ~200ms |

**Asset priority (best-to-fallback):**
- BTC / ETH / SOL: Binance → Hyperliquid → OKX → Bitget → CoinGecko
- HYPE: Hyperliquid → Binance → OKX → Bitget → CoinGecko
- XAUT: OKX → CoinGecko
- A-shares (e.g. `600519`): pytdx only (market hours: Mon–Fri 9:30–11:30 / 13:00–15:00 CST)

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   AI Agent (OpenClaw)               │
│  calls register-price-alert.py with task context   │
└───────────────────────────┬─────────────────────────┘
                            │ writes alert to JSON
                            ▼
┌─────────────────────────────────────────────────────┐
│           market-alerts.json (shared state)         │
│  ~/.openclaw/agents/{agent}/private/                │
└───────────────────────────┬─────────────────────────┘
                            │ read every 5s
                            ▼
┌─────────────────────────────────────────────────────┐
│              price-monitor.py (daemon)              │
│                                                     │
│  HTTP polling loop (5s):                            │
│    Binance → Hyperliquid → OKX → Bitget → CoinGecko │
│  A-share polling (4s, market hours):                │
│    pytdx TCP → backup servers                       │
│                                                     │
│  On condition met:                                  │
│    openclaw agent --deliver → fires MARKET_ALERT   │
└─────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────┐
│             Agent session receives:                 │
│  [MARKET_ALERT 触发 · 请处理后联系用户]              │
│  • current price + condition hit                    │
│  • context_summary from registration time           │
│  • transcript_file path for full context replay     │
└─────────────────────────────────────────────────────┘
```

**Key design choices:**

- **Polling not WebSocket for HTTP tier** — simpler reconnect logic, no session state
- **Shared JSON file** — zero IPC complexity; agent and daemon communicate via the filesystem
- **Auto-exit when no active alerts** — daemon is launched on demand, not always-on
- **One-shot alerts by default** — fires once, marks as `triggered`, stops watching
- **Context replay** — alert carries `transcript_file` + `transcript_msg_id` so agent can reconstruct exactly what the user wanted

---

## File Structure

```
market-watch/
├── SKILL.md                      # OpenClaw agent instructions (loaded by agent runtime)
├── README.md                     # This file
├── scripts/
│   ├── register-price-alert.py  # Register a new price alert + auto-start daemon
│   ├── cancel-alert.py          # List / cancel active alerts
│   ├── price-monitor.py         # Background daemon — fetches prices, checks conditions
│   ├── daemon.sh                # Process lifecycle: start / stop / restart / status / log
│   └── install-watchdog.sh      # macOS launchd watchdog (auto-restart on crash)
└── references/
    └── exchange-api.md          # WebSocket & HTTP API reference for all exchanges
```

---

## Alert Data Format

Alerts are stored in `~/.openclaw/agents/{agent}/private/market-alerts.json`:

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
      "context_summary":   "ETH exit window: sell 3.5 ETH, buy HYPE",
      "session_key":       "agent:your-agent:feishu:direct:ou_xxx",
      "agent_id":          "your-agent",
      "reply_channel":     "feishu",
      "reply_to":          "user:ou_xxx",
      "transcript_file":   "~/.openclaw/agents/{agent}/sessions/{session-id}.jsonl",
      "transcript_msg_id": "msg-id",
      "created_at":        "2026-03-12T13:00:00"
    }
  ]
}
```

**`status` lifecycle:** `active` → `triggered` (condition met) | `cancelled` (manual)

---

## For AI Agents (OpenClaw)

This skill ships with a `SKILL.md` that is automatically loaded by the OpenClaw agent runtime when the task matches the skill description. You don't need to read this README at runtime — `SKILL.md` is your reference.

**When to activate this skill:**
- User asks to "watch BTC", "alert me when ETH hits X", "盯盘", "set a price alert"
- User asks to cancel or list current alerts
- You receive a `[MARKET_ALERT 触发]` message

**Trigger flow:**
1. Parse asset, condition, target price, and user context from the conversation
2. Call `register-price-alert.py` with `--context-summary` capturing the user's intent
3. Confirm to user: "Alert set. I'll notify you when [asset] [condition] [target]."
4. When `[MARKET_ALERT 触发]` arrives in your session: read `context_summary`, optionally replay `transcript_file`, then contact the user proactively

**Non-standard assets (e.g. PEPE, new listings):**
- Add the asset to `ASSET_EXCHANGES` in `price-monitor.py`
- Add its symbol mapping to the relevant exchange fetcher
- Restart the daemon: `bash daemon.sh restart --agent {agent}`

---

## Runtime Files

| File | Path | Description |
|------|------|-------------|
| Alerts DB | `~/.openclaw/agents/{agent}/private/market-alerts.json` | Shared alert state |
| PID file | `/tmp/market-watch-{agent}.pid` | Daemon process ID |
| Log file | `/tmp/market-watch-{agent}.log` | Rotating log (max 512KB × 3) |
| Watchdog plist | `~/Library/LaunchAgents/com.openclaw.market-watch.{agent}.plist` | macOS launchd config |

---

## Requirements

- Python 3.10+
- `requests` (`pip3 install requests`)
- `pytdx` for A-share support (`pip3 install pytdx`) — optional
- [OpenClaw](https://github.com/openclaw) agent runtime (for `openclaw agent --deliver`)
- macOS or Linux (launchd watchdog is macOS-only; Linux users can use `cron` instead)

---

## License

MIT
