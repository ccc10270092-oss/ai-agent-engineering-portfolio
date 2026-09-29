"""统一安全调用包装（G-5 故障率 0 的核心保障）。

所有工具调用、LLM 调用、内容生成流程统一经 ``safe_call`` 执行：
- 失败自动重试（固定/指数退避，间隔可配）；
- 重试耗尽后不向上抛异常，返回 :class:`DegradedResult` 或降级值；
- 全链路失败路径都返回明确结果，保证上层状态机可收敛到 done。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from .logger import get_logger

log = get_logger("app_core.safe_call")


@dataclass
class DegradedResult:
    """降级结果：标识一次调用最终失败后返回的兜底值。"""

    value: Any = None
    reason: str = ""
    degraded: bool = True


def safe_call(
    fn: Callable,
    *args: Any,
    retries: int = 2,
    delay: float = 1.0,
    backoff: float = 2.0,
    degraded_value: Any = None,
    on_failure: str = "degrade",
    **kwargs: Any,
) -> Any:
    """调用 ``fn(*args, **kwargs)``，失败重试，最终失败按 ``on_failure`` 处理。

    :param retries: 重试次数（共执行 retries+1 次）。
    :param delay: 首次重试前的等待秒数。
    :param backoff: 退避乘子，第 n 次等待 ``delay * backoff^(n-1)``。
    :param degraded_value: 降级时返回的值。
    :param on_failure: ``"degrade"``（默认，返回 DegradedResult）或 ``"raise"``。
    """
    attempt = 0
    while True:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - 统一收口，不向上抛
            attempt += 1
            if attempt <= retries:
                wait = delay * (backoff ** (attempt - 1))
                log.warning("调用失败，第 %s/%s 次重试（等待 %.1fs）：%s", attempt, retries, wait, exc)
                time.sleep(wait)
                continue
            log.error("调用最终失败，执行降级：%s", exc)
            if on_failure == "raise":
                raise
            return DegradedResult(value=degraded_value, reason=str(exc))