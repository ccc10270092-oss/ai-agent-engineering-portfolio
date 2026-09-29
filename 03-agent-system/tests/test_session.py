"""会话隔离测试（G-4 / AC-06.1）：不同会话上下文互不可见。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app_core.models import MessageRole  # noqa: E402
from app_core.session import SessionStore  # noqa: E402


class TestSessionIsolation(unittest.TestCase):
    def test_two_sessions_isolated(self):
        store = SessionStore()
        s1 = store.create()
        s2 = store.create()
        store.add_message(s1.session_id, MessageRole.USER, "A 的私密咨询")
        store.add_message(s2.session_id, MessageRole.USER, "B 的私密咨询")

        h1 = store.history(s1.session_id)
        h2 = store.history(s2.session_id)

        self.assertTrue(all(m.session_id == s1.session_id for m in h1))
        self.assertTrue(all(m.session_id == s2.session_id for m in h2))
        self.assertTrue(all(m.content != "B 的私密咨询" for m in h1))
        self.assertTrue(all(m.content != "A 的私密咨询" for m in h2))

    def test_many_sessions_full_isolation(self):
        """多会话逐条校验归属，证明隔离覆盖率 100%。"""
        store = SessionStore()
        sessions = [store.create() for _ in range(5)]
        for i, s in enumerate(sessions):
            for j in range(3):
                store.add_message(s.session_id, MessageRole.USER, f"消息-{i}-{j}")

        for i, s in enumerate(sessions):
            for m in store.history(s.session_id):
                self.assertEqual(m.session_id, s.session_id)
                self.assertTrue(
                    m.content.startswith(f"消息-{i}-"),
                    f"会话 {s.session_id} 泄漏了其它会话的消息：{m.content}",
                )

    def test_history_returns_copy(self):
        """历史返回副本，外部篡改不影响存储。"""
        store = SessionStore()
        s = store.create()
        store.add_message(s.session_id, MessageRole.USER, "原始")
        store.history(s.session_id).clear()
        self.assertEqual(len(store.history(s.session_id)), 1)


class TestServiceSessionIsolation(unittest.TestCase):
    def test_ask_records_per_session_history(self):
        """集成：System.ask 在会话内记录用户/助手消息，且不跨会话泄漏。"""
        from service import System

        system = System()
        system.ingest_doc("售后服务", "本店所有产品支持 7 天无理由退换，整机保修一年。")

        system.ask("sess-a", "你们的售后政策是怎么样的？")
        system.ask("sess-b", "智能门锁 S1 的价格？")

        ha = system.session_history("sess-a")
        hb = system.session_history("sess-b")
        self.assertEqual(len(ha), 2)  # 用户 + 助手
        self.assertEqual(len(hb), 2)

        joined_a = " ".join(m.content for m in ha)
        self.assertIn("售后", joined_a)
        self.assertNotIn("智能门锁 S1 的价格", joined_a)


if __name__ == "__main__":
    unittest.main()