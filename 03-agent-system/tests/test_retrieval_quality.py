"""检索质量评测测试（对应 FR-07 / G-2 / AC-02.1 / AC-02.2 / AC-07.3）。

在同一评测集上执行「FTS5 单引擎 / 向量单引擎 / 混合融合」三路检索：
- 断言混合检索命中率 ≥ 85%（G-2 硬指标）；
- 断言混合检索不劣于任一单引擎（提供「融合优于单引擎」的对比证据）。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retrieval.eval import load_eval_data, run_eval  # noqa: E402


class TestRetrievalQuality(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_eval_data()
        cls.report = run_eval(cls.data, top_k=5)

    def test_eval_set_is_meaningful(self):
        """评测集至少 10 条查询、3 篇知识，保证统计有意义。"""
        self.assertGreaterEqual(len(self.data["queries"]), 10)
        self.assertGreaterEqual(len(self.data["knowledge"]), 3)

    def test_hybrid_hit_rate_meets_threshold(self):
        """G-2：混合检索命中率 ≥ 85%。"""
        rate = self.report["hybrid"]["rate"]
        self.assertGreaterEqual(
            rate, 0.85,
            f"混合检索命中率 {rate*100:.1f}% 未达 85% 门槛，明细：{self.report['details']}",
        )

    def test_hybrid_not_worse_than_single_engine(self):
        """AC-02.2：融合结果不低于任一单引擎（对比证据）。"""
        hybrid = self.report["hybrid"]["rate"]
        fts = self.report["fts"]["rate"]
        vector = self.report["vector"]["rate"]
        self.assertGreaterEqual(hybrid, fts, f"混合({hybrid}) < FTS({fts})")
        self.assertGreaterEqual(hybrid, vector, f"混合({hybrid}) < 向量({vector})")

    def test_single_engines_independently_retrievable(self):
        """AC-02.3：FTS5 与向量两路均可独立检索到内容。"""
        self.assertGreater(self.report["fts"]["hits"], 0)
        self.assertGreater(self.report["vector"]["hits"], 0)


if __name__ == "__main__":
    unittest.main()