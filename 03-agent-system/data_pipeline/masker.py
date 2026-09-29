"""PII 脱敏（BR-03.4 / G-3）：按规则库对文本字段做掩码或替换。"""
from __future__ import annotations

import re

from app_core.models import (
    MaskReport,
    MaskRule,
    MaskStrategy,
    PiiType,
    new_id,
    utcnow,
)

from .cleaner import TEXT_FIELDS
from .rules import DEFAULT_RULES


def _mask_match(value: str, rule: MaskRule) -> str:
    if rule.mask_strategy == MaskStrategy.REPLACE:
        return f"<{rule.pii_type.value.upper()}>"

    if rule.pii_type == PiiType.PHONE:
        return value[:3] + "****" + value[-4:] if len(value) >= 7 else "***"
    if rule.pii_type == PiiType.ID_CARD:
        return value[:6] + "*" * 8 + value[-4:] if len(value) >= 14 else "***"
    return "***"


def mask(
    records: list[dict],
    rules: list[MaskRule] | None = None,
    sample_limit: int = 5,
) -> tuple[list[dict], MaskReport]:
    """对记录中所有文本字段执行脱敏，返回 (脱敏后记录, 脱敏报告)。"""
    rules = [r for r in (rules or DEFAULT_RULES) if r.enabled]
    report = MaskReport(
        total_records=len(records),
        mask_hits={},
        masked_count={},
        samples=[],
    )
    masked_records: list[dict] = []
    samples: list[dict] = []

    for rec in records:
        new_rec = dict(rec)
        for field, value in rec.items():
            if field not in TEXT_FIELDS or not isinstance(value, str):
                continue
            for rule in rules:
                key = rule.pii_type.value
                # 在“已按前序规则脱敏”的累积结果上匹配，避免身份证内部片段被手机号重复命中
                matches = re.findall(rule.pattern, new_rec[field])
                if not matches:
                    continue
                report.mask_hits[key] = report.mask_hits.get(key, 0) + len(matches)
                report.masked_count[key] = report.masked_count.get(key, 0) + len(matches)
                new_rec[field] = re.sub(
                    rule.pattern,
                    lambda m: _mask_match(m.group(0), rule),
                    new_rec[field],
                )
                if len(samples) < sample_limit and matches:
                    samples.append({
                        "field": field,
                        "pii_type": key,
                        "before": matches[0],
                        "after": _mask_match(matches[0], rule),
                    })
        masked_records.append(new_rec)

    report.samples = samples
    return masked_records, report


def run_pipeline(records: list[dict]) -> tuple[list[dict], MaskReport]:
    """端到端管道：清洗 → 去重 → 脱敏（会话切分由上游按需调用）。

    报告额外携带 ``stage_stats``：输入 / 清洗丢弃 / 去重删除 / 最终输出，
    供前端漏斗可视化与审计核对。
    """
    from .cleaner import clean
    from .dedupe import dedupe

    cleaned = clean(records)
    deduped = dedupe(cleaned)
    masked, report = mask(deduped)
    report.stage_stats = {
        "input": len(records),
        "clean_dropped": len(records) - len(cleaned),
        "dedupe_removed": len(cleaned) - len(deduped),
        "output": len(masked),
    }
    return masked, report