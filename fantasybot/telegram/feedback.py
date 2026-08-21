"""User feedback, bug reporting, and suggestions tracker."""

import json
import os
import time
from typing import Dict, Any, Optional
from .. import config

FEEDBACK_PATH = os.path.join(config.ROOT, ".state", "feedback.jsonl")


def record_feedback(
    chat_id: int,
    user_info: Dict[str, Any],
    feedback_type: str,
    message: str
) -> Dict[str, Any]:
    """Records a user bug report or suggestion to local persistent storage."""
    os.makedirs(os.path.dirname(FEEDBACK_PATH), exist_ok=True)
    entry = {
        "timestamp": time.time(),
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "chat_id": chat_id,
        "username": user_info.get("username"),
        "first_name": user_info.get("first_name"),
        "type": feedback_type,
        "message": message,
    }
    with open(FEEDBACK_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def load_all_feedback() -> list:
    if not os.path.exists(FEEDBACK_PATH):
        return []
    results = []
    with open(FEEDBACK_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    results.append(json.loads(line))
                except Exception:
                    pass
    return results
