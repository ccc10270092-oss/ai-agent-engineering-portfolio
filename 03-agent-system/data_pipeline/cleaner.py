"""数据清洗（BR-03.1）：处理空值、异常值、格式。"""
from __future__ import annotations

import math

TEXT_FIELDS = ("content", "text", "message", "content_text")


def clean(records: list[dict]) -> list[dict]:
    """规范化文本字段并丢弃空记录。"""
    out: list[dict] = []
    for raw in records:
        rec = dict(raw)
        for key in list(rec.keys()):
            value = rec[key]
            # None 与 NaN 都视为空：pandas 读 CSV 空单元格得到 float nan，不是 None
            if value is None or (isinstance(value, float) and math.isnan(value)):
                rec[key] = ""
            elif isinstance(value, str):
                rec[key] = " ".join(value.split())  # 去除空白、折叠换行
        # 丢弃所有文本字段均为空的记录
        if _is_empty(rec):
            continue
        out.append(rec)
    return out


def _is_empty(rec: dict) -> bool:
    text_values = [str(rec.get(f, "")) for f in TEXT_FIELDS]
    return all(not v.strip() for v in text_values)