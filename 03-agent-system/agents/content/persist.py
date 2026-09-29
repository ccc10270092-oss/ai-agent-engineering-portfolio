"""Checkpointer：工作流状态持久化与断点恢复（BR-05.2）。"""
from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from pathlib import Path

from app_core.logger import get_logger

log = get_logger("agents.content.persist")


def _json_default(obj):
    """把 dataclass 中的 datetime / Enum 转成可 JSON 序列化的原生类型。"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    raise TypeError(f"不可序列化类型：{type(obj).__name__}")


class Checkpointer:
    def __init__(self, path: str = "./data/checkpoints"):
        self.path = Path(path)

    def save(self, task_id: str, state: dict) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / f"{task_id}.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )
        log.info("Checkpointer 保存状态：%s", task_id)

    def load(self, task_id: str) -> dict | None:
        file = self.path / f"{task_id}.json"
        if not file.exists():
            return None
        return json.loads(file.read_text(encoding="utf-8"))

    def delete(self, task_id: str) -> None:
        file = self.path / f"{task_id}.json"
        if file.exists():
            file.unlink()