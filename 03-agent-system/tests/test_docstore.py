"""DocRegistry 测试：upsert 幂等（保留首次时间）、查询 / 删除 / 清空 / 统计。"""
import tempfile
import unittest
from pathlib import Path

from app_core.models import KnowledgeDoc
from retrieval.docstore import DocRegistry


def _doc(doc_id: str, title: str) -> KnowledgeDoc:
    return KnowledgeDoc(title=title, content=f"{title} 的正文内容", source="测试", doc_id=doc_id)


class TestDocRegistry(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.reg = DocRegistry(Path(self.dir.name) / "docs.db")

    def tearDown(self):
        self.reg.close()
        self.dir.cleanup()

    def test_upsert_and_get(self):
        entry = self.reg.upsert(_doc("d1", "智能门锁"), chunks=3)
        self.assertEqual(entry, {
            "doc_id": "d1", "title": "智能门锁", "source": "测试",
            "chunks": 3, "created_at": entry["created_at"],
        })
        self.assertEqual(self.reg.get("d1")["title"], "智能门锁")
        self.assertIsNone(self.reg.get("nope"))

    def test_upsert_same_id_updates_keeps_created_at(self):
        first = self.reg.upsert(_doc("d1", "智能门锁"), chunks=3)
        second = self.reg.upsert(_doc("d1", "智能门锁（修订）"), chunks=5)
        self.assertEqual(second["created_at"], first["created_at"])  # 首次入库时间保留
        self.assertEqual(second["chunks"], 5)
        self.assertEqual(second["title"], "智能门锁（修订）")
        docs, chunks = self.reg.totals()
        self.assertEqual((docs, chunks), (1, 5))  # upsert 不新增行

    def test_list_ordering_newest_first(self):
        self.reg.upsert(_doc("d1", "第一篇"), chunks=1)
        self.reg.upsert(_doc("d2", "第二篇"), chunks=1)
        titles = [d["title"] for d in self.reg.list()]
        self.assertEqual(titles, ["第二篇", "第一篇"])

    def test_delete(self):
        self.reg.upsert(_doc("d1", "智能门锁"), chunks=1)
        self.assertTrue(self.reg.delete("d1"))
        self.assertFalse(self.reg.delete("d1"))  # 再删返回 False
        self.assertEqual(self.reg.list(), [])

    def test_clear_and_totals(self):
        self.reg.upsert(_doc("d1", "A"), chunks=2)
        self.reg.upsert(_doc("d2", "B"), chunks=3)
        self.assertEqual(self.reg.totals(), (2, 5))
        self.assertEqual(self.reg.clear(), 2)
        self.assertEqual(self.reg.totals(), (0, 0))

    def test_persistence_across_instances(self):
        self.reg.upsert(_doc("d1", "智能门锁"), chunks=3)
        again = DocRegistry(Path(self.dir.name) / "docs.db")
        totals = again.totals()
        title = again.list()[0]["title"]
        again.close()
        self.assertEqual(totals, (1, 3))
        self.assertEqual(title, "智能门锁")


if __name__ == "__main__":
    unittest.main()
