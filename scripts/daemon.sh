#!/bin/bash
# daemon.sh — market-watch 守护进程管理
#
# 用法:
#   daemon.sh start   [--agent laok]
#   daemon.sh stop    [--agent laok]
#   daemon.sh restart [--agent laok]
#   daemon.sh status  [--agent laok]
#   daemon.sh log     [--agent laok] [--lines N]

set -euo pipefail

AGENT="${PRICE_WATCH_AGENT:-laok}"
ACTION="${1:-status}"
shift || true
LOG_LINES=40

while [[ $# -gt 0 ]]; do
    case "$1" in
        --agent)  AGENT="$2";      shift 2 ;;
        --lines)  LOG_LINES="$2";  shift 2 ;;
        *)        shift ;;
    esac
done

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MONITOR_PY="$SKILL_DIR/scripts/price-monitor.py"
ALERTS_FILE="$HOME/.openclaw/agents/$AGENT/private/market-alerts.json"
PID_FILE="/tmp/market-watch-${AGENT}.pid"
LOG_FILE="/tmp/market-watch-${AGENT}.log"

# ── Helpers ───────────────────────────────────────────────────────────────────

is_running() {
    [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

show_alerts() {
    [[ -f "$ALERTS_FILE" ]] || return
    python3 - "$ALERTS_FILE" << 'EOF'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
    active = [a for a in data.get("alerts", []) if a.get("status") == "active"]
    price  = [a for a in active if a.get("type", "price") == "price"]
    news   = [a for a in active if a.get("type") == "news"]
    print(f"  活跃警报: {len(active)} 个  (价格:{len(price)} 新闻:{len(news)})")
    for a in active[:10]:
        if a.get("type", "price") == "price":
            print(f"    · {a['asset']} {a['condition']} {a['target_price']}  [{a.get('context_summary','')[:40]}]")
        else:
            kw = ', '.join(a.get('keywords', [])[:3])
            print(f"    · NEWS: {kw}  [{a.get('context_summary','')[:40]}]")
    if len(active) > 10:
        print(f"    ... 还有 {len(active)-10} 个")
except Exception as e:
    print(f"  (无法读取警报文件: {e})")
EOF
}

# ── Actions ───────────────────────────────────────────────────────────────────

case "$ACTION" in

    start)
        if is_running; then
            echo "[market-watch] 已在运行 PID=$(cat "$PID_FILE") agent=$AGENT"
            show_alerts
            exit 0
        fi
        mkdir -p "$(dirname "$ALERTS_FILE")"
        # 日志轮转由 Python RotatingFileHandler 管理，stdout/stderr 丢弃避免双写
        nohup python3 "$MONITOR_PY" \
            --agent "$AGENT" \
            --alerts-file "$ALERTS_FILE" \
            > /dev/null 2>&1 &
        echo $! > "$PID_FILE"
        sleep 1
        if is_running; then
            echo "[market-watch] 已启动 agent=$AGENT PID=$(cat "$PID_FILE")"
            echo "  日志: $LOG_FILE"
            show_alerts
        else
            echo "[market-watch] ❌ 启动失败"
            echo "最后 10 行日志:"
            tail -10 "$LOG_FILE" 2>/dev/null
            exit 1
        fi
        ;;

    stop)
        if is_running; then
            PID=$(cat "$PID_FILE")
            kill "$PID" 2>/dev/null && rm -f "$PID_FILE"
            echo "[market-watch] 已停止 PID=$PID"
        else
            echo "[market-watch] 未运行"
            rm -f "$PID_FILE"
        fi
        ;;

    restart)
        bash "$0" stop --agent "$AGENT"   || true
        sleep 1
        bash "$0" start --agent "$AGENT"
        ;;

    status)
        if is_running; then
            PID=$(cat "$PID_FILE")
            START_TIME=$(ps -p "$PID" -o lstart= 2>/dev/null | xargs || echo "未知")
            echo "[market-watch] ✅ 运行中 PID=$PID  agent=$AGENT"
            echo "  启动时间: $START_TIME"
            show_alerts
        else
            echo "[market-watch] ⛔ 未运行  agent=$AGENT"
            echo "  启动: bash $0 start --agent $AGENT"
        fi
        ;;

    log)
        if [[ -f "$LOG_FILE" ]]; then
            echo "=== 最近 $LOG_LINES 行日志 ($LOG_FILE) ==="
            tail -"$LOG_LINES" "$LOG_FILE"
        else
            echo "（日志文件不存在: $LOG_FILE）"
        fi
        ;;

    ensure)
        # 有活跃警报且未运行 → 启动；无活跃警报 → 不动
        HAS_ACTIVE=0
        if [[ -f "$ALERTS_FILE" ]]; then
            HAS_ACTIVE=$(python3 -c "
import json
data = json.load(open('$ALERTS_FILE'))
active = [a for a in data.get('alerts',[]) if a.get('status')=='active']
print(len(active))
" 2>/dev/null || echo 0)
        fi
        if [[ "$HAS_ACTIVE" -gt 0 ]]; then
            if ! is_running; then
                echo "[market-watch] $HAS_ACTIVE 个活跃警报，守护进程未运行，正在拉起..."
                bash "$0" start --agent "$AGENT"
            fi
        fi
        ;;

    *)
        echo "用法: daemon.sh {start|stop|restart|status|log|ensure} [--agent AGENT] [--lines N]"
        exit 1
        ;;
esac
