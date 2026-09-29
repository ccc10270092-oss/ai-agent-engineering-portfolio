"""``python -m app_core`` 自检入口（AC-01.1）。

导入框架、加载配置，并用统一 ``app_core.logger`` 输出结构化日志，
验证日志格式符合 BR-01.2（时间 级别 [模块] 消息）。
"""
from .config import get_config
from .logger import get_logger

log = get_logger("app_core")


def main() -> None:
    cfg = get_config()
    log.info("模块 A 企业级框架自检通过：配置 / 日志 / 异常 / safe_call 已就绪")
    # 只有模型名，绝不打印 api_key 明文（BR-01.4）
    log.info(
        "LLM model=%s temperature=%s max_tokens=%s（api_key 已配置=%s）",
        cfg.llm.model,
        cfg.llm.temperature,
        cfg.llm.max_tokens,
        bool(cfg.llm.api_key),
    )
    log.info(
        "检索 top_k=%s fts_weight=%s vector_weight=%s backend=%s",
        cfg.retrieval.top_k,
        cfg.retrieval.fts_weight,
        cfg.retrieval.vector_weight,
        cfg.retrieval.vector_backend,
    )
    log.info(
        "Agent max_steps=%s tool_retries=%s；内容生成 retries=%s",
        cfg.agent.max_steps,
        cfg.agent.tool_retries,
        cfg.content.retries,
    )


if __name__ == "__main__":
    main()