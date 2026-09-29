"""数据模型（全部使用 dataclass + typing 强类型，满足 BR-01.1）。

约定：
- 所有 ID 使用 uuid4 字符串；
- 时间戳统一使用 UTC；
- 数值 / 比例使用明确的 float（检索分数）或 Decimal（金额类）；
- 布尔开关使用 bool。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4


def new_id() -> str:
    """生成 uuid4 字符串 ID。"""
    return str(uuid4())


def utcnow() -> datetime:
    """返回带 UTC 时区的当前时间。"""
    return datetime.now(timezone.utc)


class SessionStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class PiiType(str, Enum):
    PHONE = "phone"
    ID_CARD = "id_card"
    EMAIL = "email"


class MaskStrategy(str, Enum):
    MASK = "mask"
    REPLACE = "replace"


class ContentStage(str, Enum):
    TOPIC = "topic"
    COPY = "copy"
    SCRIPT = "script"


class ContentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Session:
    """会话。"""

    user_id: str = ""
    session_id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    status: SessionStatus = SessionStatus.ACTIVE
    meta: dict = field(default_factory=dict)


@dataclass
class Message:
    """消息。"""

    role: MessageRole
    content: str
    session_id: str = field(default_factory=new_id)
    message_id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utcnow)
    source_chunks: list = field(default_factory=list)
    trace: list = field(default_factory=list)


@dataclass
class Chunk:
    """文档切片。"""

    text: str
    chunk_id: str = field(default_factory=new_id)
    doc_id: str = ""
    chunk_index: int = 0
    chunk_size: int = 0
    overlap: int = 0


@dataclass
class KnowledgeDoc:
    """知识文档。"""

    title: str
    content: str
    source: str = ""
    doc_id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utcnow)
    chunks: list = field(default_factory=list)


@dataclass
class RetrievedChunk:
    """检索命中的切片（含双路得分与融合得分）。"""

    chunk_id: str
    doc_id: str
    text: str
    fts_score: float = 0.0
    vector_score: float = 0.0
    final_score: float = 0.0
    rank: int = 0


@dataclass
class MaskRule:
    """PII 脱敏规则。"""

    pii_type: PiiType
    pattern: str
    mask_strategy: MaskStrategy = MaskStrategy.MASK
    enabled: bool = True
    rule_id: str = field(default_factory=new_id)


@dataclass
class MaskReport:
    """脱敏报告。"""

    total_records: int = 0
    mask_hits: dict = field(default_factory=dict)      # pii_type -> 命中次数
    masked_count: dict = field(default_factory=dict)   # pii_type -> 脱敏次数
    samples: list = field(default_factory=list)        # 抽样样本（脱敏前后对照）
    stage_stats: dict = field(default_factory=dict)    # 管道各阶段计数（仅 run_pipeline 填充）
    report_id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class GeneratedContent:
    """内容生成结果。"""

    session_id: str
    stage: ContentStage
    content: str
    status: ContentStatus = ContentStatus.PENDING
    task_id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utcnow)