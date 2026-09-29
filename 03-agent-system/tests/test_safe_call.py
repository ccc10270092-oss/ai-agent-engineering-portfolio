"""safe_call 重试 / 降级测试（对应 G-5，整体故障率 0）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app_core.safe_call import safe_call, DegradedResult  # noqa: E402


class TestSafeCall(unittest.TestCase):
    def test_success_no_retry(self):
        calls = {"n": 0}

        def ok():
            calls["n"] += 1
            return "ok"

        self.assertEqual(safe_call(ok, retries=2, delay=0), "ok")
        self.assertEqual(calls["n"], 1)

    def test_retries_then_degrade(self):
        calls = {"n": 0}

        def fail():
            calls["n"] += 1
            raise RuntimeError("boom")

        result = safe_call(fail, retries=2, delay=0, degraded_value="fallback")
        self.assertIsInstance(result, DegradedResult)
        self.assertEqual(result.value, "fallback")
        self.assertEqual(calls["n"], 3)  # 1 次原始 + 2 次重试

    def test_raise_on_failure(self):
        def fail():
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            safe_call(fail, retries=0, delay=0, on_failure="raise")


if __name__ == "__main__":
    unittest.main()