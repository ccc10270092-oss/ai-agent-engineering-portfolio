"""FTSIndex 测试：落盘持久化、按文档删除/清空、重复写入不累积、倒排后端。"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app_core.models import Chunk
from retrieval.fts import FTSIndex


def _chunk(doc_id: str, text: str, chunk_id: str | None = None) -> Chunk:
    return Chunk(text=text, doc_id=doc_id, chunk_id=chunk_id or f"{doc_id}-c1")


class TestFTSPersistence(unittest.TestCase):
    def setUp(self):
        # Windows 下 sqlite/chroma 句柄未释放会锁住文件，忽略清理残留
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Path(self.dir.name) / "fts.db"
        self.idx: FTSIndex | None = None

    def tearDown(self):
        if self.idx is not None:
            self.idx.close()
        self.dir.cleanup()

    def test_file_backed_survives_new_instance(self):
        self.idx = FTSIndex(self.db)
        self.idx.add(_chunk("doc-1", "智能门锁 S1 支持指纹开锁"))
        self.idx.commit()
        probe = FTSIndex(self.db)
        hits = probe.search("门锁")
        probe.close()
        self.assertTrue(hits)
        self.assertEqual(hits[0]["doc_id"], "doc-1")

    def test_remove_deletes_both_tables(self):
        self.idx = FTSIndex(self.db)
        self.idx.add(_chunk("doc-1", "智能门锁 指纹"))
        self.idx.add(_chunk("doc-2", "扫地机器人 激光导航"))
        self.idx.commit()

        removed = self.idx.remove("doc-1")
        self.assertEqual(removed, 1)
        self.assertFalse(any(h["doc_id"] == "doc-1" for h in self.idx.search("门锁")))
        # 第二个实例（模拟重启）同样看不到已删文档
        probe = FTSIndex(self.db)
        still_visible = any(h["doc_id"] == "doc-1" for h in probe.search("门锁"))
        probe.close()
        self.assertFalse(still_visible)
        self.assertTrue(self.idx.search("扫地"))

    def test_clear_empties_index(self):
        self.idx = FTSIndex(self.db)
        self.idx.add(_chunk("doc-1", "智能门锁"))
        self.idx.add(_chunk("doc-2", "扫地机器人"))
        self.idx.commit()
        self.idx.clear()
        self.assertEqual(self.idx.search("门锁"), [])
        probe = FTSIndex(self.db)
        hits = probe.search("机器人")
        probe.close()
        self.assertEqual(hits, [])

    def test_readd_same_chunk_no_duplicate(self):
        self.idx = FTSIndex(self.db)
        chunk = _chunk("doc-1", "重复内容", chunk_id="fixed-id")
        self.idx.add(chunk)
        self.idx.add(chunk)
        self.idx.commit()
        count = self.idx.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        self.assertEqual(count, 1)
        hits = self.idx.search("重复")
        self.assertEqual(len([h for h in hits if h["chunk_id"] == "fixed-id"]), 1)


class TestFTSInvertedBackend(unittest.TestCase):
    """FTS5 不可用时的倒排索引后端同样支持 remove / clear。"""

    def _make(self) -> FTSIndex:
        with mock.patch.object(FTSIndex, "_supports_fts5", return_value=False):
            idx = FTSIndex(":memory:")
        self.assertEqual(idx.backend, "inverted")
        return idx

    def test_search_remove_clear(self):
        idx = self._make()
        idx.add(_chunk("doc-1", "智能门锁 指纹"))
        idx.add(_chunk("doc-2", "扫地机器人"))
        self.assertTrue(idx.search("门锁"))

        removed = idx.remove("doc-1")
        self.assertGreaterEqual(removed, 1)  # 倒排索引按 token 计数（智能门锁指纹 = 6）
        self.assertFalse(idx.search("门锁"))
        self.assertTrue(idx.search("扫地"))

        idx.clear()
        self.assertEqual(idx.search("扫地"), [])


if __name__ == "__main__":
    unittest.main()
