"""向量存储测试：remove / clear、ChromaDB 持久化与维度守卫。

Chroma 用例在 chromadb 未安装时跳过；全部离线（特征哈希向量或假 embedder）。
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

from app_core.models import Chunk
from retrieval.vector import SimpleVectorStore


def _chunk(doc_id: str, text: str, chunk_id: str) -> Chunk:
    return Chunk(text=text, doc_id=doc_id, chunk_id=chunk_id)


class TestSimpleVectorStore(unittest.TestCase):
    def setUp(self):
        self.store = SimpleVectorStore()

    def test_remove_only_target_doc(self):
        self.store.add(_chunk("d1", "智能门锁指纹", "d1-c1"))
        self.store.add(_chunk("d2", "扫地机器人", "d2-c1"))
        self.store.remove("d1")
        hits = self.store.search("门锁")
        self.assertFalse(any(h["doc_id"] == "d1" for h in hits))
        self.assertTrue(self.store.search("扫地"))

    def test_clear(self):
        self.store.add(_chunk("d1", "智能门锁", "d1-c1"))
        self.store.clear()
        self.assertEqual(self.store.search("门锁"), [])
        self.assertEqual(self.store._vecs, [])


@unittest.skipUnless(importlib.util.find_spec("chromadb"), "chromadb 未安装")
class TestChromaVectorStore(unittest.TestCase):
    def setUp(self):
        from retrieval.vector import ChromaVectorStore

        self._cls = ChromaVectorStore
        # chromadb 的 HNSW 段文件为 mmap 打开，Windows 下无法在句柄存活时删除
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = str(Path(self.dir.name) / "chroma")

    def tearDown(self):
        self.dir.cleanup()

    def test_persist_remove_clear(self):
        store = self._cls(path=self.path)
        store.add(_chunk("d1", "智能门锁指纹开锁", "d1-c1"))
        store.add(_chunk("d2", "扫地机器人激光导航", "d2-c1"))

        # 新实例（模拟重启）能查到
        again = self._cls(path=self.path)
        self.assertTrue(any(h["doc_id"] == "d1" for h in again.search("门锁")))

        again.remove("d1")
        self.assertFalse(any(h["doc_id"] == "d1" for h in again.search("门锁")))
        self.assertTrue(any(h["doc_id"] == "d2" for h in again.search("扫地")))

        again.clear()
        self.assertEqual(again._collection.count(), 0)

    def test_dimension_guard_resets_on_mismatch(self):
        # 先写入 256 维哈希向量
        store = self._cls(path=self.path)
        store.add(_chunk("d1", "旧维度向量", "d1-c1"))
        self.assertEqual(store._collection.count(), 1)

        # 换 512 维 embedder 打开同一目录 → 守卫应重置向量库
        def embed_512(text: str) -> list[float]:
            return [0.1] * 512

        store2 = self._cls(path=self.path, embed=embed_512)
        self.assertEqual(store2._collection.count(), 0)  # 旧 256 维向量已清

        # 重置后可用新维度正常入库
        store2.add(_chunk("d2", "新维度向量", "d2-c1"))
        self.assertTrue(store2.search("新维度"))


if __name__ == "__main__":
    unittest.main()
