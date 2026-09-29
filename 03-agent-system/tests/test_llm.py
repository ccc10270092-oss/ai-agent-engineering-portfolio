"""LLM 客户端测试：生成出口统一剥离 emoji（真实/Mock 全路径）。

覆盖 _strip_emoji 纯函数（常见 emoji / 旗帜 / ZWJ 组合 / 键帽 / 变体选择符 /
常规文本不受影响）与 LLMClient.generate 出口（真实返回路径 + Mock 全模式端到端）。
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 直跑本文件（不经 run_tests.py）时同样强制离线。
for _key in ("LLM_API_KEY", "LLM_BASE_URL", "OPENAI_API_KEY", "OPENAI_BASE_URL"):
    os.environ[_key] = ""

from app_core.config import LLMConfig  # noqa: E402
from app_core.llm import LLMClient, MockLLM, _strip_emoji  # noqa: E402


class TestStripEmoji(unittest.TestCase):
    def test_common_emoji_removed(self):
        self.assertEqual(
            _strip_emoji("指纹一秒开门 🔑，安全感拉满 ✨🚀"),
            "指纹一秒开门，安全感拉满",
        )

    def test_flag_and_zwj_sequence_removed(self):
        self.assertEqual(_strip_emoji("国货之光 🇨🇳"), "国货之光")
        self.assertEqual(_strip_emoji("全家福 👨‍👩‍👧 来啦"), "全家福 来啦")

    def test_keycap_keeps_base_char(self):
        self.assertEqual(_strip_emoji("排名 1️⃣ 靠前"), "排名 1 靠前")

    def test_variation_selector_removed(self):
        # © 本体是合法文本符号，仅剥离 emoji 样式后缀（FE0F）
        self.assertEqual(_strip_emoji("©️ 版权所有"), "© 版权所有")

    def test_plain_text_untouched(self):
        text = "智能门锁 S1，售价 899 元；支持指纹、密码开锁。\n第二行参数。"
        self.assertEqual(_strip_emoji(text), text)

    def test_trailing_emoji_and_standalone_line(self):
        self.assertEqual(_strip_emoji("再也不用摸黑翻包找钥匙 🔑"), "再也不用摸黑翻包找钥匙")
        self.assertEqual(_strip_emoji("第一行\n🔑\n第二行"), "第一行\n\n第二行")


class _EmojiImpl:
    """模拟真实模型返回带 emoji 的文本。"""

    def generate(self, messages, mode="chat", **overrides):
        return "从换上智能门锁 S1 开始 🔑 全家安心 ✨"


class TestGenerateStripsEmoji(unittest.TestCase):
    """LLMClient.generate 出口剥离：替换 _impl 模拟真实模型返回。"""

    def setUp(self):
        self.client = LLMClient(LLMConfig(api_key="", base_url=""))  # Mock 装配
        self.client._impl = _EmojiImpl()

    def test_real_path_stripped(self):
        out = self.client.generate([{"role": "user", "content": "q"}], mode="copy")
        self.assertEqual(out, "从换上智能门锁 S1 开始 全家安心")

    def test_mock_end_to_end_no_emoji(self):
        self.client._impl = MockLLM(LLMConfig())
        for mode in ("answer", "topic", "copy", "script", "chat"):
            out = self.client.generate(
                [{"role": "user", "content": "用户问题：智能门锁 S1 价格"}], mode=mode
            )
            self.assertTrue(out)
            self.assertEqual(out, _strip_emoji(out))


if __name__ == "__main__":
    unittest.main()
