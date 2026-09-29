from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from app.config import ROOT_DIR


POLICY_FILE = ROOT_DIR / "data" / "policies.json"
_POLICIES: list[dict[str, str]] | None = None


def _load_policies() -> list[dict[str, str]]:
    global _POLICIES
    if _POLICIES is None:
        _POLICIES = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    return _POLICIES


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for part in re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+", text.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", part):
            if len(part) == 1:
                tokens.append(part)
            else:
                tokens.extend(part[index : index + 2] for index in range(len(part) - 1))
        else:
            tokens.append(part)
    return tokens


def search_policy(query: str, limit: int = 3) -> dict[str, Any]:
    policies = _load_policies()
    query_tokens = tokenize(query)
    if not query_tokens:
        return {"results": [], "message": "没有识别到可用于检索的关键词。"}

    documents = [tokenize(f"{item['title']} {item['category']} {item['content']}") for item in policies]
    document_frequency: Counter[str] = Counter()
    for tokens in documents:
        document_frequency.update(set(tokens))
    average_length = sum(map(len, documents)) / max(len(documents), 1)
    query_frequency = Counter(query_tokens)
    scored: list[tuple[float, dict[str, str]]] = []

    for policy, tokens in zip(policies, documents):
        frequencies = Counter(tokens)
        score = 0.0
        for token, qf in query_frequency.items():
            tf = frequencies[token]
            if not tf:
                continue
            df = document_frequency[token]
            idf = math.log(1 + (len(documents) - df + 0.5) / (df + 0.5))
            k1, b = 1.5, 0.75
            denominator = tf + k1 * (1 - b + b * len(tokens) / max(average_length, 1))
            score += idf * (tf * (k1 + 1) / denominator) * min(qf, 2)
        if score > 0:
            scored.append((score, policy))

    scored.sort(key=lambda item: item[0], reverse=True)
    results = [
        {
            "id": policy["id"],
            "title": policy["title"],
            "category": policy["category"],
            "source": policy["source"],
            "quote": policy["content"],
            "score": round(score, 3),
        }
        for score, policy in scored[: max(1, min(limit, 5))]
    ]
    return {"results": results, "message": "本地 BM25 检索结果；回答时请基于这些政策内容并引用条款。"}
