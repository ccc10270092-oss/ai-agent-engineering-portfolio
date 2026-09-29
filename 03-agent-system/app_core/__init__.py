"""模块 A：企业级框架。

提供全局配置、日志、异常体系、数据模型与统一安全调用包装（safe_call）。
所有其它模块都通过本包获取基础能力。
"""
from .config import load_config, get_config, AppConfig
from .logger import get_logger
from .safe_call import safe_call, DegradedResult
from .session import SessionStore

__all__ = [
    "load_config",
    "get_config",
    "AppConfig",
    "get_logger",
    "safe_call",
    "DegradedResult",
    "SessionStore",
]