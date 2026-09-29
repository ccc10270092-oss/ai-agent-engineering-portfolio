"""会话切分（BR-03.3）：按 session_id 或时间窗口切分独立会话。"""
from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4


def split_sessions(
    records: list[dict],
    id_field: str = "session_id",
    time_field: str = "timestamp",
    time_gap_minutes: int = 30,
) -> list[dict]:
    """返回 list[{"session_id": str, "messages": list[dict], ...}]。

    优先按 ``id_field`` 分组；若缺失，则按 ``time_field`` 的时间间隔切分，
    相邻记录间隔超过 ``time_gap_minutes`` 即视为新会话。
    """
    if not records:
        return []

    has_id = any(str(rec.get(id_field, "")).strip() for rec in records)
    if has_id:
        return _split_by_id(records, id_field)
    return _split_by_time(records, time_field, time_gap_minutes)


def _split_by_id(records: list[dict], id_field: str) -> list[dict]:
    sessions: dict = {}
    order: list = []
    for rec in records:
        sid = str(rec.get(id_field, "")).strip() or "default"
        if sid not in sessions:
            sessions[sid] = {"session_id": sid, "messages": []}
            order.append(sid)
        sessions[sid]["messages"].append(rec)
    return [sessions[s] for s in order]


def _split_by_time(records: list[dict], time_field: str, gap_minutes: int) -> list[dict]:
    sessions: list[dict] = []
    current = None
    prev_ts = None
    gap = timedelta(minutes=gap_minutes)

    for rec in records:
        ts = _parse(rec.get(time_field))
        if current is None or _gap_exceeded(prev_ts, ts, gap):
            current = {"session_id": str(uuid4()), "messages": []}
            sessions.append(current)
        current["messages"].append(rec)
        if ts is not None:
            prev_ts = ts
    return sessions


def _parse(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value).strip(), fmt)
        except ValueError:
            continue
    return None


def _gap_exceeded(prev, cur, gap) -> bool:
    if prev is None or cur is None:
        return False
    return (cur - prev) > gap