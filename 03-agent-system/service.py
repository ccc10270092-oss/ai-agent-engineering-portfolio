"""系统门面：把配置、LLM、检索、两个 Agent 组装成可直接调用的服务。

demo.py 与 frontend 都通过本类复用同一套装配逻辑，避免重复初始化。

知识库三份状态（FTS 全文 / 向量 / 文档登记）均持久化到 data/ 下，
重启不丢；文档按 doc_id（标题+内容决定论哈希）三路同增删。
"""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path

from app_core.config import load_config, get_config, AppConfig, PROJECT_ROOT
from app_core.llm import LLMClient
from app_core.logger import get_logger
from app_core.models import (
    ContentStage,
    GeneratedContent,
    KnowledgeDoc,
    Message,
    MessageRole,
    RetrievedChunk,
    Session,
)
from app_core.session import SessionStore
from data_pipeline.masker import run_pipeline
from retrieval.docstore import DocRegistry
from retrieval.fts import FTSIndex
from retrieval.hybrid import HybridRetriever
from retrieval.vector import get_vector_store
from agents.content.graph import ContentAgent
from agents.content.persist import Checkpointer
from agents.pre_sale.catalog_store import ProductStore, detect_product
from agents.pre_sale.graph import ReActAgent, AgentAnswer
from agents.pre_sale.tools import Tools

log = get_logger("service")


class System:
    """智能 AI Agent 售前服务系统的统一入口。"""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root).resolve() if root else PROJECT_ROOT
        self.config: AppConfig = load_config(Path(root) if root else None)
        self.llm = LLMClient(self.config.llm)

        ret = self.config.retrieval
        self.fts = FTSIndex(self._data_path(ret.fts_db))
        self.docs = DocRegistry(self._data_path(ret.docs_db))
        self.vector = get_vector_store(ret)
        self.retriever = HybridRetriever(
            self.fts,
            self.vector,
            chunk_size=ret.chunk_size,
            overlap=ret.chunk_overlap,
            top_k=ret.top_k,
            fts_weight=ret.fts_weight,
            vector_weight=ret.vector_weight,
        )

        # 商品目录（SQLite 持久化，首次启动自动写入内置种子）
        self.products = ProductStore(self._data_path(self.config.products.products_db))
        self.products.seed_if_empty()
        self.tools = Tools(self.retriever, self.products)
        self.pre_sale = ReActAgent(
            self.llm,
            self.tools,
            max_steps=self.config.agent.max_steps,
            tool_retries=self.config.agent.tool_retries,
        )
        self.content_agent = ContentAgent(
            self.llm, retries=self.config.content.retries, checkpointer=Checkpointer()
        )
        self.sessions = SessionStore()

    def _data_path(self, path: str) -> Path:
        """数据文件相对路径按项目根解析，避免从其他 CWD 启动时另建一套库。"""
        p = Path(path)
        return p if p.is_absolute() else self.root / p

    # ---- 数据管道 ----
    def process_data(self, records: list[dict]):
        """清洗 → 去重 → PII 脱敏，返回 (脱敏后记录, 脱敏报告)。"""
        return run_pipeline(records)

    # ---- 会话管理（FR-06 / G-4）----
    def create_session(self, user_id: str = "") -> Session:
        return self.sessions.create(user_id)

    def list_sessions(self) -> list[Session]:
        return self.sessions.list()

    def session_history(self, session_id: str) -> list[Message]:
        return self.sessions.history(session_id)

    # ---- 检索 ----
    def ingest_doc(self, title: str, content: str, source: str = "") -> dict:
        """入库文档（幂等），返回登记条目并附 product 字段。

        doc_id = md5(长度前缀|标题|内容)：同 title+content 重复入库覆盖不累积；
        改动内容则视为新文档（旧条目保留，可另行删除）。
        标题/内容命中产品文档启发式时自动登记商品，entry["product"] 为商品条目
        （同名更新、内容未变零写入、手动管理过的商品不覆盖），否则为 None。
        """
        doc_id = hashlib.md5(  # noqa: S324 - 非安全场景，仅作内容寻址
            f"{len(title)}|{title}|{content}".encode("utf-8")
        ).hexdigest()
        doc = KnowledgeDoc(
            title=title,
            content=content,
            source=source or "手动录入",
            doc_id=doc_id,
        )
        chunks = self.retriever.ingest(doc)
        entry = self.docs.upsert(doc, chunks)
        entry["product"] = self._maybe_register_product(title, content, doc_id)
        return entry

    def _maybe_register_product(self, title: str, content: str, doc_id: str) -> dict | None:
        """产品文档启发式自动登记商品；失败只告警，绝不影响入库主流程。"""
        try:
            detected = detect_product(title, content)
            if detected is None:
                return None
            return self.products.register_from_doc(detected, doc_id)
        except Exception as exc:  # noqa: BLE001 - 自动登记是增强能力，不能拖垮入库
            log.warning("商品自动登记失败（%s），文档入库不受影响", exc)
            return None

    def search(self, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
        return self.retriever.search(query, top_k)

    # ---- 知识库管理（FR-02 增强：列表 / 删除 / 清空，全部持久化）----
    def list_docs(self) -> list[dict]:
        """已入库文档登记（SQLite 持久化，重启不丢）。"""
        return self.docs.list()

    def delete_doc(self, doc_id: str) -> dict | None:
        """删除文档（FTS + 向量 + 登记三路同删）；不存在返回 None。"""
        entry = self.docs.get(doc_id)
        if entry is None:
            return None
        self.retriever.remove(doc_id)
        self.docs.delete(doc_id)
        log.info("文档 %s 已删除", entry["title"])
        return entry

    def clear_knowledge(self) -> dict:
        """清空知识库三路状态，返回清理统计。"""
        docs, chunks = self.docs.totals()
        self.docs.clear()
        self.fts.clear()
        try:
            self.vector.clear()
        except Exception as exc:  # noqa: BLE001 - 向量清理失败不阻断清空主流程
            log.warning("向量库清空失败（%s），可重启后重试或删除对应目录", exc)
        log.info("知识库已清空（%d 篇文档 / %d 个切片）", docs, chunks)
        return {"cleared_docs": docs, "cleared_chunks": chunks}

    # ---- 商品目录（持久化 + 自动登记 + 管理）----
    def list_products(self) -> list[dict]:
        """全部商品（编号正序），供内容生成页与 /api/products。"""
        return self.products.list()

    def add_product(self, name: str, specs: str = "", category: str = "",
                    price: float | None = None, stock: int = 100) -> dict:
        """手动新增商品；同名抛 ValueError（API 层转 400）。"""
        return self.products.create(name, specs, category, price, stock)

    def update_product(self, product_id: str, fields: dict) -> dict | None:
        """手动编辑商品（转为 origin=manual，不再被文档登记覆盖）；
        改名撞他人名称抛 ValueError；不存在返回 None（API 层转 404）。"""
        return self.products.update(product_id, fields)

    def delete_product(self, product_id: str) -> dict | None:
        """删除商品；关联的知识文档不受影响。不存在返回 None。"""
        return self.products.delete(product_id)

    # ---- 售前咨询 ----
    def ask(self, session_id: str, query: str) -> AgentAnswer:
        """售前咨询：记录用户消息，携带会话历史推理，记录回答（G-4 隔离）。"""
        self.sessions.add_message(session_id, MessageRole.USER, query)
        history = [
            {"role": m.role.value, "content": m.content}
            for m in self.sessions.history(session_id)
        ]
        ans = self.pre_sale.run(session_id, query, history=history)
        self.sessions.add_message(
            session_id, MessageRole.ASSISTANT, ans.answer, ans.source_chunks, ans.trace
        )
        return ans

    # ---- 内容生成 ----
    def generate_content(
        self, session_id: str, product_info: dict, stage: str = "all"
    ) -> list[GeneratedContent]:
        enriched = {**product_info, **self.build_grounding(product_info)}
        return self.content_agent.generate(session_id, enriched, stage)

    def build_grounding(self, product_info: dict) -> dict:
        """内容生成接地信息：商品参数串 + 知识库 top-k 检索片段。

        返回 {"specs", "references"}；reference 为 {"doc_id","title","text"} 纯字典
        （可进 Checkpointer JSON）。失败只告警并返回空接地，绝不阻断生成主流程。
        """
        info = product_info or {}
        try:
            pid = (info.get("product_id") or "").strip()
            name = (info.get("name") or "").strip()
            entry = (self.products.get(pid) if pid else None) or (
                self.products.find_by_name(name) if name else None
            )
            parts = []
            if entry:
                if entry.get("specs"):
                    parts.append(entry["specs"])
                if entry.get("category"):
                    parts.append(f"分类:{entry['category']}")
                if entry.get("price") is not None:
                    parts.append(f"价格 {entry['price']} 元")
            specs = ";".join(parts)

            def _clean(text: str) -> str:
                # 抹掉提示词标记「用户问题：」(全/半角冒号都处理),防止 MockLLM _extract_query 误取标记行
                cleaned = str(text or "").replace("用户问题：", "问：").replace("用户问题:", "问:")
                return " ".join(cleaned.split())

            references = []
            query = name or pid
            if query:
                for hit in self.retriever.search(query, self.config.retrieval.top_k):
                    title = _clean((self.docs.get(hit.doc_id) or {}).get("title", ""))
                    references.append(
                        {"doc_id": hit.doc_id, "title": title, "text": _clean(hit.text)[:200]}
                    )
            return {"specs": specs, "references": references}
        except Exception as exc:  # noqa: BLE001 - 接地是增强能力,失败按无接地继续
            log.warning("内容生成接地信息构建失败(%s),按无接地继续生成", exc)
            return {"specs": "", "references": []}


# 进程内单例，供演示与前端复用（加锁防 FastAPI 线程池冷启动竞态）
_instance: System | None = None
_instance_lock = threading.Lock()


def get_system() -> System:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = System()
    return _instance