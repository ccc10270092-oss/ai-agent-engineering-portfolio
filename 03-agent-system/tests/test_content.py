"""内容生成 Agent 测试（对应 FR-05：三阶段、失败跳过、Checkpointer 恢复、RAG 接地）。"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 直跑本文件（不经 run_tests.py）时同样强制离线 + 各库指向临时目录。
# 必须在 import service（间接装配 System 依赖）之前设置。
for _key in ("LLM_API_KEY", "LLM_BASE_URL", "OPENAI_API_KEY", "OPENAI_BASE_URL"):
    os.environ[_key] = ""
os.environ["EMBEDDING_BACKEND"] = "hash"
os.environ["RETRIEVAL_VECTOR_BACKEND"] = "simple"
_content_test_data = tempfile.mkdtemp(prefix="agent-system-content-tests-")
os.environ["RETRIEVAL_FTS_DB"] = os.path.join(_content_test_data, "fts.db")
os.environ["RETRIEVAL_DOCS_DB"] = os.path.join(_content_test_data, "docs.db")
os.environ["RETRIEVAL_CHROMA_PATH"] = os.path.join(_content_test_data, "chroma")
os.environ["PRODUCTS_DB"] = os.path.join(_content_test_data, "products.db")

from app_core.config import LLMConfig  # noqa: E402
from app_core.llm import LLMClient  # noqa: E402
from app_core.models import ContentStage, ContentStatus  # noqa: E402
from agents.content import stages  # noqa: E402
from agents.content.graph import ContentAgent  # noqa: E402
from agents.content.persist import Checkpointer  # noqa: E402
from service import System  # noqa: E402


class TestContentAgent(unittest.TestCase):
    def setUp(self):
        self.agent = ContentAgent(LLMClient(LLMConfig()), retries=1)

    def test_generates_three_stages(self):
        results = self.agent.generate("s", {"name": "智能门锁 S1"}, stage="all")
        self.assertEqual(
            [r.stage for r in results],
            [ContentStage.TOPIC, ContentStage.COPY, ContentStage.SCRIPT],
        )
        self.assertTrue(all(r.status == ContentStatus.DONE for r in results))
        self.assertTrue(all(r.content for r in results))

    def test_single_stage(self):
        results = self.agent.generate("s", {"name": "X"}, stage="copy")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].stage, ContentStage.COPY)

    def test_stage_failure_skips_node(self):
        def boom(llm, product_info):
            raise RuntimeError("gen fail")

        with patch.dict(stages.STAGE_GENERATORS, {ContentStage.TOPIC: boom}):
            results = self.agent.generate("s", {"name": "X"}, stage="topic")
        self.assertEqual(results[0].status, ContentStatus.FAILED)
        self.assertEqual(results[0].content, "")


class TestCheckpointer(unittest.TestCase):
    def test_roundtrip_and_delete(self):
        cp = Checkpointer(path="./data/checkpoints")
        cp.save("t1", {"a": 1})
        self.assertEqual(cp.load("t1"), {"a": 1})
        cp.delete("t1")
        self.assertIsNone(cp.load("t1"))


class TestResume(unittest.TestCase):
    def test_resume_persists_progress(self):
        """resume 后新完成阶段回写检查点：再次 resume 不重跑已完成阶段。"""
        with tempfile.TemporaryDirectory() as tmp:
            agent = ContentAgent(
                LLMClient(LLMConfig()), retries=1, checkpointer=Checkpointer(path=tmp)
            )
            state = {
                "session_id": "s",
                "product": {"product_id": "P001", "name": "智能门锁 S1"},
                "task_id": "t-resume",
                "stages": {
                    "topic": {
                        "session_id": "s",
                        "stage": "topic",
                        "content": "已有选题",
                        "status": "done",
                        "task_id": "t-resume",
                        "created_at": "2026-01-01T00:00:00+00:00",
                    }
                },
            }
            agent.checkpointer.save("t-resume", state)

            results = agent.resume("t-resume", {"product_id": "P001"})
            self.assertEqual(
                {r.stage for r in results}, {ContentStage.COPY, ContentStage.SCRIPT}
            )

            saved = agent.checkpointer.load("t-resume")
            self.assertEqual(set(saved["stages"]), {"topic", "copy", "script"})
            self.assertEqual(saved["stages"]["topic"]["status"], "done")
            self.assertEqual(saved["stages"]["copy"]["status"], "done")

            # 全部阶段完成后再次 resume：无剩余阶段可跑
            self.assertEqual(agent.resume("t-resume", {"product_id": "P001"}), [])


class TestGroundingPrompt(unittest.TestCase):
    """提示词组合：接地块注入；无接地键时与旧版逐字节一致（向后兼容钉子）。"""

    def test_legacy_prompt_unchanged(self):
        self.assertEqual(
            stages._prompt("生成 3 个选题。", {"name": "X"}),
            "为产品【X】生成 3 个选题。用户问题：X",
        )
        self.assertEqual(
            stages._prompt("生成推广文案。", {"product_id": "P001"}),
            "为产品【P001】生成推广文案。用户问题：P001",
        )

    def test_grounding_injected_before_marker(self):
        info = {
            "name": "智能门锁 S1",
            "specs": "指纹+密码开锁;价格 899 元",
            "references": [
                {"doc_id": "d1", "title": "智能门锁 S1 参数", "text": "续航一年"},
                {"doc_id": "d2", "title": "", "text": "支持远程开锁"},
                {"doc_id": "d3", "title": "空文本片段", "text": "   "},
            ],
        }
        prompt = stages._prompt("生成推广文案。", info)
        self.assertIn("产品参数：指纹+密码开锁;价格 899 元", prompt)
        self.assertIn("参考资料：", prompt)
        self.assertIn("【检索片段】续航一年（来源：智能门锁 S1 参数）", prompt)
        self.assertIn("【检索片段】支持远程开锁", prompt)  # 无标题不带来源括号
        self.assertNotIn("空文本片段", prompt)  # 空白文本片段整体跳过
        self.assertTrue(prompt.endswith("用户问题：智能门锁 S1"))  # 标记保持末行
        self.assertLess(prompt.index("产品参数"), prompt.index("用户问题："))  # 接地在前


class TestBuildGrounding(unittest.TestCase):
    """System.build_grounding：商品参数 + 知识库检索片段 + 失败兜底。"""

    @classmethod
    def setUpClass(cls):
        cls.system = System()

    def _ingest(self, title, content):
        entry = self.system.ingest_doc(title, content, "接地测试")
        self.addCleanup(self.system.delete_doc, entry["doc_id"])
        return entry

    def test_specs_and_references(self):
        entry = self._ingest(
            "grounding-test 门锁售后保修说明",  # 标题含负向词,不触发商品登记
            "智能门锁 S1 支持指纹、密码开锁，电池续航一年，保修两年。",
        )
        g = self.system.build_grounding({"product_id": "P001", "name": "智能门锁 S1"})
        self.assertTrue(g["specs"])  # 种子 P001 参数
        self.assertIn("899", g["specs"])  # 价格注入
        self.assertIn(entry["doc_id"], [r["doc_id"] for r in g["references"]])
        self.assertTrue(all(r.get("text") for r in g["references"]))

    def test_marker_stripped_from_references(self):
        self._ingest(
            "grounding-marker 门锁售后咨询",
            "智能门锁 S1 常见咨询：用户问题：怎么远程开门？答：APP 内点击远程开锁。",
        )
        g = self.system.build_grounding({"name": "智能门锁 S1"})
        self.assertTrue(g["references"])
        self.assertTrue(all("用户问题" not in r["text"] for r in g["references"]))
        self.assertTrue(all("用户问题" not in r["title"] for r in g["references"]))

    def test_unknown_product_tolerated(self):
        g = self.system.build_grounding({"product_id": "P999", "name": "绝不存在的商品XYZ"})
        self.assertEqual(g["specs"], "")
        self.assertIsInstance(g["references"], list)

    def test_empty_input(self):
        self.assertEqual(
            self.system.build_grounding({}), {"specs": "", "references": []}
        )

    def test_broken_retriever_degrades(self):
        with patch.object(self.system.retriever, "search", side_effect=RuntimeError("boom")):
            g = self.system.build_grounding({"product_id": "P001", "name": "智能门锁 S1"})
        self.assertEqual(g, {"specs": "", "references": []})
        # 接地失败不阻断生成
        results = self.system.generate_content(
            "s-ground", {"product_id": "P001", "name": "智能门锁 S1"}, stage="topic"
        )
        self.assertEqual(results[0].status, ContentStatus.DONE)
        self.assertTrue(results[0].content)


if __name__ == "__main__":
    unittest.main()