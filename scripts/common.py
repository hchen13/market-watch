"""
common.py — 公共工具函数

price-monitor.py 和 news-monitor.py 共享的工具函数：
  - get_session_uuid: 通过 session_key 查询 sessionId
  - deliver_message:  通过 openclaw agent --deliver 发送通知
  - atomic_write_json: 原子替换方式写 JSON（防并发损坏）
"""

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def get_session_uuid(session_key: str, agent_id: str) -> Optional[str]:
    """通过 session_key 查询对应的 sessionId（用于 --session-id 参数）"""
    try:
        result = subprocess.run(
            ["openclaw", "sessions", "--agent", agent_id, "--json"],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(result.stdout)
        for s in data.get("sessions", []):
            if s.get("key") == session_key:
                return s.get("sessionId")
    except Exception:
        pass
    return None


def deliver_message(alert: dict, msg: str) -> None:
    """
    通过 openclaw agent 注入消息到 agent session（不自动投递）。

    链路：news-monitor/price-monitor 命中 → 注入 agent main session →
    agent 精筛判断 → agent 自行决定是否用 message 工具通知用户。

    不使用 --deliver：避免 NO_REPLY 等 agent 内部响应被自动推送到用户飞书。
    路由到 agent main session（--agent），不绑定用户 DM session。
    """
    agent_id      = alert.get("agent_id", "laok")
    reply_channel = alert.get("reply_channel", "feishu")
    reply_to      = alert.get("reply_to", "")

    # 注入到 agent main session，由 agent 决定是否联系用户
    # prompt 中包含 reply_channel/reply_to 信息供 agent 使用 message 工具时参考
    enriched_msg = msg
    if reply_channel and reply_to:
        enriched_msg += (
            f"\n\n[投递信息]\n"
            f"如需通知用户，请使用 message 工具：\n"
            f"  channel: {reply_channel}\n"
            f"  accountId: {agent_id}\n"
            f"  target: {reply_to}\n"
        )

    cmd = ["openclaw", "agent",
           "--agent", agent_id,
           "--message", enriched_msg]

    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def atomic_write_json(path: Path, data: object) -> None:
    """
    原子替换方式写 JSON 文件。
    先写到同目录下的临时文件，再用 os.replace 原子替换，
    防止多进程并发写入时文件损坏。
    """
    with tempfile.NamedTemporaryFile(
        "w", dir=str(path.parent), delete=False, suffix=".tmp",
        encoding="utf-8",
    ) as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        tmp = f.name
    os.replace(tmp, str(path))
