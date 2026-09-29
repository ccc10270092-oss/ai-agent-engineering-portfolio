"""知识库端到端行为测试（System 级，临时库由 run_tests.py 环境变量重定向）。

核心验收：入库 → 新 System 实例（模拟重启）→ 登记与检索仍在；
幂等重录不累积；删除/清空三路一致。
"""
import os
import unittest

from service import System

_UNIQUE = "kb-test-"


def _system() -> System:
    return System()


def _clear_all():
    _system().clear_knowledge()


class TestKnowledgeBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _clear_all()

    def test_persist_across_restart(self):
        s1 = _system()
        entry = s1.ingest_doc(
            f"{_UNIQUE}门锁文档", "智能门锁 S1 售价 899 元，支持指纹开锁。", "测试"
        )
        self.assertTrue(entry["doc_id"])
        self.assertGreaterEqual(entry["chunks"], 1)

        s2 = _system()  # 模拟服务重启：新实例、同一持久化库
        listed = s2.list_docs()
        self.assertTrue(any(d["doc_id"] == entry["doc_id"] for d in listed))
        hits = s2.search("门锁 价格")
        self.assertTrue(any(h.doc_id == entry["doc_id"] for h in hits))

    def test_ingest_idempotent(self):
        s = _system()
        e1 = s.ingest_doc(f"{_UNIQUE}幂等", "同一文档重复入库应覆盖，不累积副本。")
        e2 = s.ingest_doc(f"{_UNIQUE}幂等", "同一文档重复入库应覆盖，不累积副本。")
        self.assertEqual(e1["doc_id"], e2["doc_id"])  # doc_id 决定论
        # 只验证本测试文档不重复（套件内其他用例共享同一临时库）
        same = [d for d in s.list_docs() if d["title"] == f"{_UNIQUE}幂等"]
        self.assertEqual(len(same), 1)
        self.assertGreaterEqual(same[0]["chunks"], 1)

    def test_delete_removes_from_all_three_stores(self):
        s = _system()
        entry = s.ingest_doc(f"{_UNIQUE}待删除", "扫地机器人 R3 采用激光导航，吸力 5000Pa。")
        doc_id = entry["doc_id"]

        deleted = s.delete_doc(doc_id)
        self.assertIsNotNone(deleted)
        self.assertIsNone(s.delete_doc(doc_id))  # 再删 → None

        s2 = _system()
        self.assertFalse(any(d["doc_id"] == doc_id for d in s2.list_docs()))
        self.assertFalse(any(h.doc_id == doc_id for h in s2.search("扫地机器人")))
        self.assertFalse(any(c.doc_id == doc_id for c in s2.fts.search("扫地机器人")))

    def test_clear(self):
        s = _system()
        s.ingest_doc(f"{_UNIQUE}清空前", "智能音箱 M2 售价 399 元。")
        result = s.clear_knowledge()
        self.assertGreaterEqual(result["cleared_docs"], 1)
        self.assertEqual(s.list_docs(), [])
        self.assertEqual(s.search("智能音箱"), [])
        self.assertEqual(s.docs.totals(), (0, 0))

    def test_edited_doc_is_new_entry(self):
        s = _system()
        e1 = s.ingest_doc(f"{_UNIQUE}修订", "版本一的内容")
        e2 = s.ingest_doc(f"{_UNIQUE}修订", "版本二的内容")
        self.assertNotEqual(e1["doc_id"], e2["doc_id"])  # 内容变 → 新文档
        titles = [d["title"] for d in s.list_docs() if d["title"] == f"{_UNIQUE}修订"]
        self.assertEqual(len(titles), 2)
        s.delete_doc(e1["doc_id"])  # 清理旧版本


if __name__ == "__main__":
    unittest.main()
