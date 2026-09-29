"""统一配置（满足 BR-01.4）。

优先级：环境变量 > .env 文件 > config.yaml > 默认值。

- 非敏感配置（检索参数、Agent 步数等）来自 config.yaml；
- 敏感配置（LLM API Key / Base URL / 模型名）仅来自 .env 或环境变量，
  绝不落库、不写日志、不传前端。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class LLMConfig:
    model: str = "mock"                 # "mock" 表示离线降级，无 Key 也可跑
    max_tokens: int = 2048
    temperature: float = 0.2
    api_key: str = ""
    base_url: str = ""
    api_format: str = ""                # anthropic | openai；留空=按 Base URL 自动识别


@dataclass
class RateLimitConfig:
    base_delay: float = 1.0
    max_retries: int = 2


@dataclass
class RetrievalConfig:
    top_k: int = 5
    fts_weight: float = 0.5
    vector_weight: float = 0.5
    chunk_size: int = 512
    chunk_overlap: int = 64
    vector_backend: str = "chroma"      # "chroma" | "simple"（chromadb 未装时回退 simple）
    embedding_backend: str = ""         # ""=自动（三项齐→api，否则 hash） | "local" | "api" | "hash"
    embedding_model: str = ""           # 留空=内置特征哈希；api 填 OpenAI 兼容模型名，local 填本地模型名
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    fts_db: str = "data/fts.db"         # FTS5 索引库（":memory:" = 不持久化）
    docs_db: str = "data/docs.db"       # 知识文档登记库
    chroma_path: str = "data/chroma"    # ChromaDB 向量库目录


@dataclass
class AgentConfig:
    max_steps: int = 10
    tool_retries: int = 2


@dataclass
class ContentConfig:
    retries: int = 3


@dataclass
class ProductsConfig:
    products_db: str = "data/products.db"   # 商品目录库（首次启动自动写入内置种子）


@dataclass
class AppConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    content: ContentConfig = field(default_factory=ContentConfig)
    products: ProductsConfig = field(default_factory=ProductsConfig)


def _load_dotenv(path: Path) -> dict:
    """最小 .env 解析，避免额外依赖。支持行内注释与引号。"""
    if not path.exists():
        return {}
    out: dict = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if value and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1]
        out[key.strip()] = value
    return out


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore
    except ImportError:
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or {}


def _apply_nested(cfg: AppConfig, data: dict) -> None:
    """把 config.yaml 的扁平分组映射到 AppConfig 的同名字段。"""
    for group_name, group_cfg in data.items():
        if not isinstance(group_cfg, dict) or not hasattr(cfg, group_name):
            continue
        target = getattr(cfg, group_name)
        for key, value in group_cfg.items():
            if hasattr(target, key) and value is not None:
                setattr(target, key, value)
    # 保持双路权重归一化语义（设计与测试依赖 0~1 权重）
    if cfg.retrieval.fts_weight + cfg.retrieval.vector_weight == 0:
        cfg.retrieval.fts_weight = cfg.retrieval.vector_weight = 0.5


def load_config(root: Path | None = None) -> AppConfig:
    """加载并缓存配置。"""
    root = Path(root) if root else PROJECT_ROOT
    cfg = AppConfig()

    yaml_data = _load_yaml(root / "config.yaml")
    _apply_nested(cfg, yaml_data)

    env = {**_load_dotenv(root / ".env"), **os.environ}
    # 敏感三项只从环境 /.env 读取
    if env.get("LLM_MODEL"):
        cfg.llm.model = env["LLM_MODEL"]
    if env.get("LLM_API_KEY") or env.get("OPENAI_API_KEY"):
        cfg.llm.api_key = env.get("LLM_API_KEY") or env.get("OPENAI_API_KEY", "")
    if env.get("LLM_BASE_URL") or env.get("OPENAI_BASE_URL"):
        cfg.llm.base_url = env.get("LLM_BASE_URL") or env.get("OPENAI_BASE_URL", "")
    if env.get("LLM_API_FORMAT"):
        cfg.llm.api_format = env["LLM_API_FORMAT"]
    if env.get("RETRIEVAL_VECTOR_BACKEND"):
        cfg.retrieval.vector_backend = env["RETRIEVAL_VECTOR_BACKEND"]
    if env.get("EMBEDDING_BACKEND"):
        cfg.retrieval.embedding_backend = env["EMBEDDING_BACKEND"]
    if env.get("RETRIEVAL_FTS_DB"):
        cfg.retrieval.fts_db = env["RETRIEVAL_FTS_DB"]
    if env.get("RETRIEVAL_DOCS_DB"):
        cfg.retrieval.docs_db = env["RETRIEVAL_DOCS_DB"]
    if env.get("RETRIEVAL_CHROMA_PATH"):
        cfg.retrieval.chroma_path = env["RETRIEVAL_CHROMA_PATH"]
    if env.get("PRODUCTS_DB"):
        cfg.products.products_db = env["PRODUCTS_DB"]
    # embedding：显式三项优先，否则复用同一 OpenAI 兼容网关的 Key / Base URL
    if env.get("EMBEDDING_MODEL"):
        cfg.retrieval.embedding_model = env["EMBEDDING_MODEL"]
    cfg.retrieval.embedding_api_key = (
        env.get("EMBEDDING_API_KEY")
        or env.get("LLM_API_KEY")
        or env.get("OPENAI_API_KEY", "")
    )
    cfg.retrieval.embedding_base_url = (
        env.get("EMBEDDING_BASE_URL")
        or env.get("LLM_BASE_URL")
        or env.get("OPENAI_BASE_URL", "")
    )

    _cached["config"] = cfg
    return cfg


_cached: dict = {}


def get_config() -> AppConfig:
    """返回已加载配置；首次调用会自动加载。"""
    if "config" not in _cached:
        load_config()
    return _cached["config"]