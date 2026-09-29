"""知识文档登记库：SQLite 持久化文档元信息（doc_id / 标题 / 来源 / 切片数）。

与 FTS 索引、Chroma 向量库并列的第三份知识库状态，支撑：
- 重启后 ``GET /api/knowledge`` 仍有完整文档列表；
- 按文档删除（FTS / 向量 / 登记三路同删）；
- 总览统计（文档数、切片数）。

条目结构刻意与旧版 API 的内存登记表一致：{doc_id, title, source, chunks, created_at}。
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from app_core.logger import get_logger
from app_core.models import KnowledgeDoc

log = get_logger("retrieval.docstore")

_ENTRY_COLS = "doc_id, title, source, chunks, created_at"


def _row_to_entry(row: tuple) -> dict:
    return {
        "doc_id": row[0],
        "title": row[1],
        "source": row[2],
        "chunks": row[3],
        "created_at": row[4],
    }


class DocRegistry:
    """文档登记表（SQLite 单表，自带连接 / 锁 / 逐操作 commit）。"""

    def __init__(self, db_path: str | Path = "data/docs.db"):
        path = str(db_path)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS docs "
            "(doc_id TEXT PRIMARY KEY, title TEXT, source TEXT, "
            "chunks INTEGER DEFAULT 0, created_at TEXT)"
        )
        self.conn.commit()

    def upsert(self, doc: KnowledgeDoc, chunks: int) -> dict:
        """新增或更新文档登记（重复入库幂等），返回登记条目。

        ON CONFLICT 不更新 created_at，保留首次入库时间。
        """
        with self._lock:
            self.conn.execute(
                "INSERT INTO docs(doc_id, title, source, chunks, created_at) "
                "VALUES (?,?,?,?,?) "
                "ON CONFLICT(doc_id) DO UPDATE SET "
                "title=excluded.title, source=excluded.source, chunks=excluded.chunks",
                (doc.doc_id, doc.title, doc.source, chunks, doc.created_at.isoformat()),
            )
            self.conn.commit()
        entry = self.get(doc.doc_id)
        assert entry is not None  # 刚写入必定存在
        return entry

    def get(self, doc_id: str) -> dict | None:
        with self._lock:
            row = self.conn.execute(
                f"SELECT {_ENTRY_COLS} FROM docs WHERE doc_id = ?", (doc_id,)
            ).fetchone()
        return _row_to_entry(row) if row else None

    def list(self) -> list[dict]:
        """按入库时间倒序（rowid 兜底同秒排序）。"""
        with self._lock:
            rows = self.conn.execute(
                f"SELECT {_ENTRY_COLS} FROM docs ORDER BY created_at DESC, rowid DESC"
            ).fetchall()
        return [_row_to_entry(r) for r in rows]

    def delete(self, doc_id: str) -> bool:
        """删除登记，返回是否删除了记录。"""
        with self._lock:
            cur = self.conn.execute("DELETE FROM docs WHERE doc_id = ?", (doc_id,))
            self.conn.commit()
        return cur.rowcount > 0

    def clear(self) -> int:
        """清空登记表，返回删除条数。"""
        with self._lock:
            cur = self.conn.execute("DELETE FROM docs")
            self.conn.commit()
        return cur.rowcount

    def totals(self) -> tuple[int, int]:
        """返回 (文档数, 切片总数)。"""
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(chunks), 0) FROM docs"
            ).fetchone()
        return int(row[0]), int(row[1])

    def close(self) -> None:
        """关闭连接（测试 / 优雅停机用；Windows 下未关闭会锁住库文件）。"""
        with self._lock:
            self.conn.close()
