"""统一异常体系。

所有业务异常继承 BaseAppError；可重试的异常继承 RetryableError，
用于 safe_call 判断是否需要重试。降级类异常用于标识“已降级”的结果来源。
"""


class BaseAppError(Exception):
    """应用错误的基类。"""


class ConfigError(BaseAppError):
    """配置读取 / 校验失败。"""


class RetryableError(BaseAppError):
    """可安全重试的暂时性错误（网络抖动、限流、LLM 超时等）。"""


class ToolError(RetryableError):
    """工具调用失败。"""


class LLMError(RetryableError):
    """LLM 调用失败。"""


class RetrievalError(BaseAppError):
    """检索模块错误。"""


class DegradedError(BaseAppError):
    """标识一次调用最终失败并已执行降级（用于日志记录降级路径）。"""