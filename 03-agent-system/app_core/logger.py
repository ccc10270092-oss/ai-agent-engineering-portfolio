"""统一日志。

所有模块通过 ``app_core.logger / get_logger(模块名)`` 输出日志，
格式固定为 ``时间 级别 [模块] 消息``，满足 BR-01.2。

注意：调用方必须保证传入日志的内容已经过脱敏，
禁止直接打印 API Key 或 PII 原文。
"""
from __future__ import annotations

import logging
import sys

_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_configured = False


def _configure_root() -> None:
    global _configured
    if _configured:
        return
    # Windows 下管道/重定向默认走 locale 编码，统一为 UTF-8 避免中文乱码
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """返回以模块名命名的 logger，统一走根 handler。"""
    _configure_root()
    return logging.getLogger(name)