"""售前咨询 Agent 测试（对应 FR-04 / G-5：正常回答、工具失败降级、超步终止）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app_core.config import LLMConfig  # noqa: E402
from app_core.llm import LLMClient  # noqa: E402
from agents.pre_sale.graph import ReActAgent  # noqa: E402
from agents.pre_sale.tools import ToolAction, ToolRouter  # noqa: E402
from service import System  # noqa: E402


class TestPreSaleAgent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.system = System()
        cls.system.ingest_doc(
            "售后服务", "本店所有产品支持 7 天无理由退换，整机保修一年，全国联保。"
        )

    def _tools_used(self, ans):
        return {t.get("tool") for t in ans.trace if t.get("stage") == "acting"}

    def test_product_info_reasoning(self):
        ans = self.system.ask("s", "智能门锁 S1 的价格和参数？")
        self.assertFalse(ans.degraded)
        self.assertTrue(ans.answer)
        self.assertIn("get_product_info", self._tools_used(ans))

    def test_search_knowledge_returns_sources(self):
        ans = self.system.ask("s", "你们的售后政策是怎么样的？")
        self.assertFalse(ans.degraded)
        self.assertTrue(ans.source_chunks)
        self.assertIn("search_knowledge", self._tools_used(ans))

    def test_stock_query_uses_stock_tool(self):
        ans = self.system.ask("s", "智能音箱 M2 有库存吗？")
        self.assertFalse(ans.degraded)
        self.assertIn("get_stock", self._tools_used(ans))


class TestToolRouter(unittest.TestCase):
    def test_extract_key_chinese_adjacent(self):
        """汉字紧邻产品 ID 时也能提取（\\b 在汉字/字母间不成立，须用负向断言）。"""
        action = ToolRouter().decide("查一下P001的参数")
        self.assertEqual(action.name, "get_product_info")
        self.assertEqual(action.args["product_id"], "P001")


class TestStress(unittest.TestCase):
    """AC-04.4 / G-5：连续 100 次问答，系统崩溃次数为 0。"""

    def test_100_rounds_no_crash(self):
        system = System()
        system.ingest_doc("售后服务", "本店所有产品支持 7 天无理由退换，整机保修一年，全国联保。")
        queries = [
            "智能门锁 S1 价格和参数？",
            "扫地机器人 R3 吸力？",
            "你们的售后政策？",
            "智能音箱 M2 有库存吗？",
            "门锁支持指纹吗？",
        ] * 20  # 100 次
        for i, q in enumerate(queries):
            ans = system.ask(f"stress-{i % 5}", q)  # 不抛异常即视为自愈成功
            self.assertIsNotNone(ans.answer)
            self.assertIsNotNone(ans.trace)


class TestFaultTolerance(unittest.TestCase):
    def _agent(self, tools, max_steps=10, router=None):
        llm = LLMClient(LLMConfig())  # 离线 Mock
        return ReActAgent(llm, tools, max_steps=max_steps, tool_retries=1, router=router)

    def test_tool_failure_degrades_without_exception(self):
        class FailingTools:
            def call(self, action):
                raise RuntimeError("tool down")

        agent = self._agent(FailingTools())
        ans = agent.run("s", "随便问一句？")
        self.assertTrue(ans.degraded)
        self.assertIn("稍后", ans.answer)  # 降级话术而非抛异常

    def test_max_steps_terminates(self):
        class AlwaysRouter:
            def reset(self):
                pass

            def decide(self, query):
                return ToolAction("search_knowledge", {"query": query})

        class StubTools:
            def call(self, action):
                return []

        agent = self._agent(StubTools(), max_steps=3, router=AlwaysRouter())
        ans = agent.run("s", "问题")
        self.assertTrue(ans.degraded)
        self.assertEqual(ans.reason, "max_steps_exceeded")
        acting_steps = sum(1 for t in ans.trace if t["stage"] == "acting")
        self.assertEqual(acting_steps, 3)


if __name__ == "__main__":
    unittest.main()