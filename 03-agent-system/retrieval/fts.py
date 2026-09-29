"""SQLite-FTS5 全文检索（BR-02.1）。

优先使用 FTS5（bm25 打分），并显式按「中文逐字 / 英文逐词」分词后写入，
避免不同 SQLite 构建对 CJK 默认分词的差异；若环境未启用 FTS5 则回退为
内存倒排索引打分，保证任何环境都能跑通。

支持落盘持久化（默认 "data/fts.db"，经 HybridRetriever.ingest 统一 commit）；
FastAPI 线程池会并发访问同一连接，故所有读写都持锁。
"""
from __future__ import annotations

import re
import sqlite3
import threading
from collections import defaultdict
from pathlib import Path

from app_core.logger import get_logger
from app_core.models import Chunk

log = get_logger("retrieval.fts")


class FTSIndex:
    def __init__(self, db_path: str | Path = ":memory:"):
        path = str(db_path)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS chunks "
            "(doc_id TEXT, chunk_id TEXT PRIMARY KEY, text TEXT)"
        )
        if self._supports_fts5():
            self.backend = "fts5"
            self.conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts "
                "USING fts5(doc_id, chunk_id, text)"
            )
        else:
            self.backend = "inverted"
            self._index: dict = defaultdict(list)
            log.warning("当前 SQLite 未启用 FTS5，回退为倒排索引检索")

    def _supports_fts5(self) -> bool:
        try:
            self.conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _probe USING fts5(x)")
            self.conn.execute("DROP TABLE _probe")
            return True
        except sqlite3.OperationalError:
            return False

    def add(self, chunk: Chunk) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO chunks(doc_id, chunk_id, text) VALUES (?,?,?)",
                (chunk.doc_id, chunk.chunk_id, chunk.text),
            )
            if self.backend == "fts5":
                # 显式空格分词，让 unicode61 按 token 建索引，中文逐字可检索；
                # fts5 虚拟表不保证跨构建支持 OR REPLACE，先删后插保持可移植幂等
                self.conn.execute(
                    "DELETE FROM chunks_fts WHERE chunk_id = ?", (chunk.chunk_id,)
                )
                tokenized = " ".join(_tokens(chunk.text))
                self.conn.execute(
                    "INSERT INTO chunks_fts(doc_id, chunk_id, text) VALUES (?,?,?)",
                    (chunk.doc_id, chunk.chunk_id, tokenized),
                )
            else:
                for token in _tokens(chunk.text):
                    self._index[token].append(chunk)

    def remove(self, doc_id: str) -> int:
        """删除指定文档的全部切片，返回 chunks 表删除行数。"""
        if self.backend == "inverted":
            with self._lock:
                before = sum(len(v) for v in self._index.values())
                for token in list(self._index):
                    self._index[token] = [c for c in self._index[token] if c.doc_id != doc_id]
                    if not self._index[token]:
                        del self._index[token]
                return before - sum(len(v) for v in self._index.values())
        with self._lock:
            cur = self.conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            self.conn.execute("DELETE FROM chunks_fts WHERE doc_id = ?", (doc_id,))
            self.conn.commit()
            return cur.rowcount

    def clear(self) -> None:
        """清空全部索引（清空知识库用）。"""
        with self._lock:
            if self.backend == "fts5":
                self.conn.execute("DELETE FROM chunks")
                self.conn.execute("DELETE FROM chunks_fts")
            else:
                self._index.clear()
            self.conn.commit()

    def commit(self) -> None:
        """提交未落盘事务（批量入库由 HybridRetriever.ingest 末尾统一调用）。"""
        with self._lock:
            self.conn.commit()

    def close(self) -> None:
        """关闭连接（测试 / 优雅停机用；Windows 下未关闭会锁住库文件）。"""
        with self._lock:
            self.conn.close()

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        if self.backend == "fts5":
            return self._search_fts5(query, top_k)
        return self._search_inverted(query, top_k)

    def _search_fts5(self, query: str, top_k: int) -> list[dict]:
        tokens = _tokens(query)
        if not tokens:
            return []
        terms = " OR ".join(f'"{t}"' for t in tokens)
        with self._lock:
            rows = self.conn.execute(
                "SELECT c.doc_id, c.chunk_id, c.text, bm25(chunks_fts) AS r "
                "FROM chunks_fts JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id "
                "WHERE chunks_fts MATCH ? ORDER BY r LIMIT ?",
                (terms, top_k * 2),
            ).fetchall()
        # bm25 越小越相关（负值越负越相关），取相反数转成越大越相关
        return [
            {"chunk_id": r[1], "doc_id": r[0], "text": r[2],
             "fts_score": -float(r[3])}
            for r in rows
        ]

    def _search_inverted(self, query: str, top_k: int) -> list[dict]:
        tokens = _tokens(query)
        if not tokens:
            return []
        with self._lock:
            index_snapshot = {t: list(v) for t, v in self._index.items()}
        scores: dict = defaultdict(float)
        meta: dict = {}
        for token in tokens:
            for chunk in index_snapshot.get(token, []):
                scores[chunk.chunk_id] += 1.0
                meta[chunk.chunk_id] = chunk
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])[: top_k * 2]
        return [
            {"chunk_id": cid, "doc_id": meta[cid].doc_id,
             "text": meta[cid].text, "fts_score": score}
            for cid, score in ranked
        ]


def _tokens(text: str) -> list[str]:
    """中英文混合分词：连续英文/数字为一个 token，中文逐字为 token。"""
    return re.findall(r"[A-Za-z0-9_]+|[一-鿿]", (text or "").lower())
