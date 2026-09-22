from __future__ import annotations

"""Clean, human-readable chat transcript -- separate from the
internal debug log (logs/jarvis_runtime.log), which is full of
engineering noise (Groq key rotation, warnings, JSON parse errors)
and was never meant to be read as a conversation record. This is
the file UK can hand to anyone (including this Claude conversation)
to show JARVIS's actual behavior turn by turn, without wading
through internal telemetry to find the real exchange.
"""

import os
import re
import time
from typing import List, Optional


def read_recent_turns(n: int = 5, path: Optional[str] = None) -> List[dict]:
    """Read back the last N (user, response) pairs from the persistent
    chat log -- the CROSS-SESSION fallback for Brain.recent_turns,
    which is in-memory only and wiped on every restart. THE ACTUAL
    BUG (2026-09-11): UK restarts JARVIS often during development, so
    "JARVIS ko mera conversation kuchh nahi pata" was often literally
    true right after a restart -- the in-memory buffer really was
    empty, even though the FULL history was sitting right here in
    this file the whole time. get_recent_conversation() falls back to
    this when the in-memory buffer doesn't have enough. Best-effort:
    returns [] on any I/O/parse issue rather than raising."""
    target = path or _CHAT_LOG_PATH
    try:
        with open(target, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except Exception:
        return []
    turns: List[dict] = []
    current_user = None
    for line in lines:
        line = line.rstrip("\n")
        if not line:
            continue
        m = re.match(r"^\[[^\]]+\]\s+UK:\s*(.*)$", line)
        if m:
            current_user = m.group(1)
            continue
        m = re.match(r"^\[[^\]]+\]\s+JARVIS:\s*(.*)$", line)
        if m and current_user is not None:
            turns.append({"user_input": current_user, "response": m.group(1)})
            current_user = None
    return turns[-n:] if n else turns

_CHAT_LOG_PATH = os.path.join("logs", "chat_log.txt")


def log_chat_turn(user_input: str, response: str, path: Optional[str] = None) -> None:
    """Append one (user, JARVIS) exchange in plain, readable form.
    Silently no-ops on any I/O failure -- logging a conversation must
    never be able to break the conversation itself."""
    target = path or _CHAT_LOG_PATH
    if not user_input and not response:
        return
    try:
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] UK: {user_input}\n")
            handle.write(f"[{timestamp}] JARVIS: {response}\n\n")
    except Exception:
        pass
