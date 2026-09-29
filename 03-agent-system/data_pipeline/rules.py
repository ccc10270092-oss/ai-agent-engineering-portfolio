"""默认 PII 脱敏规则（G-3，对应 MaskRule 数据模型）。

注意顺序：身份证（18 位）必须先于手机号，否则身份证内部的
``1[3-9]XXXXXXXXX`` 片段会被手机号规则误命中、破坏整段。

边界用数字负向断言而非 ``\\b``：Python 正则视汉字为 word 字符，
``\\b`` 在「汉字紧跟数字」（如 身份证110101...）之间不成立，会导致漏检。
"""
from __future__ import annotations

from app_core.models import MaskRule, MaskStrategy, PiiType

DEFAULT_RULES: list[MaskRule] = [
    MaskRule(
        pii_type=PiiType.ID_CARD,
        pattern=r"(?<![0-9Xx])\d{17}[0-9Xx](?![0-9Xx])",
        mask_strategy=MaskStrategy.MASK,
        enabled=True,
    ),
    MaskRule(
        pii_type=PiiType.PHONE,
        pattern=r"(?<!\d)1[3-9]\d{9}(?!\d)",
        mask_strategy=MaskStrategy.MASK,
        enabled=True,
    ),
    MaskRule(
        pii_type=PiiType.EMAIL,
        pattern=r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        mask_strategy=MaskStrategy.REPLACE,
        enabled=True,
    ),
]