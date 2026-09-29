"""混合检索测试（对应 G-2，双路均可查 / AC-02.x）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app_core.models import KnowledgeDoc  # noqa: E402
from retrieval.fts import FTSIndex  # noqa: E402
from retrieval.hybrid import HybridRetriever  # noqa: E402
from retrieval.vector import SimpleVectorStore  # noqa: E402


class TestRetrieval(unittest.TestCase):
    def setUp(self):
        self.fts = FTSIndex(":memory:")
        self.vector = SimpleVectorStore()
        self.retriever = HybridRetriever(
            self.fts, self.vector, chunk_size=128, overlap=16, top_k=3
        )
        self._ingest()

    def _ingest(self):
        docs = [
            KnowledgeDoc(title="门锁", content="智能门锁 S1 指纹密码蓝牙三合一 续航一年 售价 899"),
            KnowledgeDoc(title="机器人", content="扫地机器人 R3 激光导航 吸力 5000Pa 续航 180 分钟 售价 1999"),
        ]
        for d in docs:
            self.retriever.ingest(d)

    def test_ingest_and_search(self):
        # 双路均能查到：全文索引与向量索引已写入
        self.assertGreater(len(self.fts.search("门锁")), 0)
        self.assertGreater(len(self.vector.search("门锁")), 0)

    def test_hybrid_search_returns_ranked(self):
        results = self.retriever.search("扫地机器人 R3 价格")
        self.assertTrue(results)
        self.assertEqual(results[0].rank, 1)
        self.assertTrue(all(r.final_score >= 0 for r in results))
        self.assertTrue(any("扫地" in r.text for r in results))

    def test_hybrid_merge_single_source(self):
        # 仅命中一路也能返回结果
        results = self.retriever.search("指纹")
        self.assertTrue(results)


if __name__ == "__main__":
    unittest.main()