"""工具调用重试（BR-04.4）：统一复用 safe_call，重试耗尽即降级。"""
from __future__ import annotations

from typing import Any, Callable

from app_core.safe_call import safe_call


def call_tool(
    fn: Callable,
    *args: Any,
    retries: int = 2,
    delay: float = 1.0,
    **kwargs: Any,
) -> Any:
    """调用工具：默认重试 2 次，失败返回 DegradedResult 而非抛异常。"""
    return safe_call(fn, *args, retries=retries, delay=delay, degraded_value=None, **kwargs)