"""会话管理（FR-06 / G-4）：新建 / 切换会话，历史记录按会话严格隔离。

``SessionStore`` 以 ``session_id -> list[Message]`` 键控，不同会话的消息互不
可见，满足「会话隔离覆盖率 100%」（G-4 / AC-06.1）。
"""
from __future__ import annotations

from .models import Message, MessageRole, Session, utcnow


class SessionStore:
    """进程内会话存储（单机单体，无需外部依赖）。"""

    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._messages: dict[str, list[Message]] = {}

    def create(self, user_id: str = "") -> Session:
        """新建会话并返回。"""
        s = Session(user_id=user_id)
        self._sessions[s.session_id] = s
        self._messages[s.session_id] = []
        return s

    def list(self) -> list[Session]:
        return list(self._sessions.values())

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def add_message(
        self,
        session_id: str,
        role: MessageRole,
        content: str,
        source_chunks: list | None = None,
        trace: list | None = None,
    ) -> Message:
        """追加一条消息；会话不存在时自动创建（保证 ask 可直接调用）。"""
        s = self._sessions.get(session_id)
        if s is None:
            s = Session(session_id=session_id)
            self._sessions[session_id] = s
            self._messages[session_id] = []
        msg = Message(
            role=role,
            content=content,
            session_id=session_id,
            source_chunks=source_chunks or [],
            trace=trace or [],
        )
        s.updated_at = utcnow()
        self._messages[session_id].append(msg)
        return msg

    def history(self, session_id: str) -> list[Message]:
        """返回某会话的历史（副本，防止外部直接篡改）。"""
        return list(self._messages.get(session_id, []))