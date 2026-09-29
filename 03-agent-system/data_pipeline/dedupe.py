"""去重（BR-03.2）：基于内容哈希 + 可选 token 相似度。"""
from __future__ import annotations

import hashlib
import re

from .cleaner import TEXT_FIELDS


def _content(rec: dict) -> str:
    return " | ".join(str(rec.get(f, "")) for f in TEXT_FIELDS).strip()


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _hash(text: str) -> str:
    return hashlib.md5(_norm(text).encode("utf-8")).hexdigest()  # noqa: S324


def _jaccard(a: str, b: str) -> float:
    sa, sb = set(a.split()), set(b.split())
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def dedupe(records: list[dict], similarity_threshold: float = 0.0) -> list[dict]:
    """去除完全重复（哈希）以及（可选）相似重复的记录。"""
    out: list[dict] = []
    seen: set = set()
    for rec in records:
        text = _content(rec)
        digest = _hash(text)
        if digest in seen:
            continue
        # 相似度去重：与已保留记录做 token Jaccard
        duplicate = False
        if similarity_threshold > 0:
            for kept in out:
                if _jaccard(text, _content(kept)) >= similarity_threshold:
                    duplicate = True
                    break
        if duplicate:
            continue
        seen.add(digest)
        out.append(rec)
    return out