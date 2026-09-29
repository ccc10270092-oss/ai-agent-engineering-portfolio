"""API 层数据模型与序列化工具。

后端业务模型是 dataclass（非 Pydantic），datetime / Enum 需要递归转换；
``to_jsonable`` 统一处理，路由层直接返回普通 dict。
"""
from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def to_jsonable(obj: Any) -> Any:
    """把 dataclass / Enum / datetime 递归转成 JSON 可序列化结构。"""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return str(obj)


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    user_id: str = Field(default="", max_length=64)


class IngestRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=200_000)
    source: str = Field(default="", max_length=200)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int | None = Field(default=None, ge=1, le=50)


class AskRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    query: str = Field(min_length=1, max_length=2000)


class GenerateRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    product_id: str = Field(min_length=1, max_length=32)
    name: str = Field(default="", max_length=128)
    stage: str = Field(default="all", pattern="^(all|topic|copy|script)$")


class ProductCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    specs: str = Field(default="", max_length=2000)
    category: str = Field(default="", max_length=64)
    price: float | None = Field(default=None, ge=0)
    stock: int = Field(default=100, ge=0)


class ProductUpdateRequest(BaseModel):
    """全部字段可选：None = 不修改。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    specs: str | None = Field(default=None, max_length=2000)
    category: str | None = Field(default=None, max_length=64)
    price: float | None = Field(default=None, ge=0)
    stock: int | None = Field(default=None, ge=0)


class ResumeRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=64)


class PipelineRequest(BaseModel):
    records: list[dict] = Field(min_length=1, max_length=5000)
