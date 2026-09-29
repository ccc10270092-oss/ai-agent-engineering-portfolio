"""混合检索与融合打分（BR-02.4）。"""
from __future__ import annotations

from app_core.models import Chunk, KnowledgeDoc, RetrievedChunk
from app_core.logger import get_logger

from .chunker import chunk_doc
from .fts import FTSIndex
from .vector import VectorStore

log = get_logger("retrieval.hybrid")


def _normalize(scores: list[float]) -> list[float]:
    """min-max 归一化到 [0,1]；单元素时直接给 1.0，避免除零。"""
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if hi == lo:
        return [1.0] * len(scores)
    return [(s - lo) / (hi - lo) for s in scores]


class HybridRetriever:
    def __init__(
        self,
        fts: FTSIndex,
        vector: VectorStore,
        chunk_size: int = 512,
        overlap: int = 64,
        top_k: int = 5,
        fts_weight: float = 0.5,
        vector_weight: float = 0.5,
    ):
        self.fts = fts
        self.vector = vector
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.top_k = top_k
        self.fts_weight = fts_weight
        self.vector_weight = vector_weight

    def ingest(self, doc: KnowledgeDoc) -> int:
        """文档切片并分别写入全文与向量索引，返回切片数。

        先删除该 doc_id 的旧切片再写入：重复入库 / 调整 chunk 参数后重录
        都不残留旧数据；末尾统一 commit 落盘。
        """
        self.remove(doc.doc_id)
        chunks = chunk_doc(doc, self.chunk_size, self.overlap)
        for chunk in chunks:
            self.fts.add(chunk)
            self.vector.add(chunk)
        doc.chunks = chunks
        self.fts.commit()
        log.info("文档 %s 已入库（%d 个切片）", doc.title, len(chunks))
        return len(chunks)

    def remove(self, doc_id: str) -> None:
        """从双路索引中删除指定文档的全部切片。"""
        self.fts.remove(doc_id)
        try:
            self.vector.remove(doc_id)
        except Exception as exc:  # noqa: BLE001 - 向量删除失败不阻断入库/删除主流程
            log.warning("向量索引删除文档 %s 失败（%s）", doc_id, exc)

    def search(self, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
        top_k = top_k or self.top_k
        fts_hits = self.fts.search(query, top_k)
        vec_hits = self.vector.search(query, top_k)

        # 双路得分分别归一化
        fts_map = {
            h["chunk_id"]: s
            for h, s in zip(fts_hits, _normalize([h["fts_score"] for h in fts_hits]))
        }
        vec_map = {
            h["chunk_id"]: s
            for h, s in zip(vec_hits, _normalize([h["vector_score"] for h in vec_hits]))
        }

        merged: dict[str, dict] = {}
        for h in fts_hits:
            merged[h["chunk_id"]] = {"doc_id": h["doc_id"], "text": h["text"]}
        for h in vec_hits:
            merged.setdefault(h["chunk_id"], {"doc_id": h["doc_id"], "text": h["text"]})

        results = []
        for cid, meta in merged.items():
            f = fts_map.get(cid, 0.0)
            v = vec_map.get(cid, 0.0)
            final = self.fts_weight * f + self.vector_weight * v
            results.append(
                RetrievedChunk(
                    chunk_id=cid,
                    doc_id=meta["doc_id"],
                    text=meta["text"],
                    fts_score=f,
                    vector_score=v,
                    final_score=final,
                )
            )

        results.sort(key=lambda x: -x.final_score)
        for i, r in enumerate(results[:top_k], start=1):
            r.rank = i
        return results[:top_k]