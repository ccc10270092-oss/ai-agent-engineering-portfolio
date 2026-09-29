"""PII 脱敏测试（对应 G-3，准确率 100% / AC-03.x）。"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_pipeline.masker import mask  # noqa: E402
from data_pipeline.rules import DEFAULT_RULES  # noqa: E402


class TestMasker(unittest.TestCase):
    def test_all_pii_masked(self):
        records = [
            {"content": "手机 13812345678 和 13998765432，",
             "session_id": "s1"},
            {"content": "身份证 110101199003078888，邮箱 zhangsan@example.com",
             "session_id": "s2"},
        ]
        masked, report = mask(records)
        joined = " ".join(str(r.get("content", "")) for r in masked)

        # 脱敏后不再出现任何原始 PII 模式
        for rule in DEFAULT_RULES:
            self.assertFalse(
                re.search(rule.pattern, joined),
                f"仍存在未脱敏的 {rule.pii_type.value}: {joined}",
            )

        # 报告计数正确（phone 2 + id_card 1 + email 1）
        self.assertEqual(report.mask_hits.get("phone"), 2)
        self.assertEqual(report.mask_hits.get("id_card"), 1)
        self.assertEqual(report.mask_hits.get("email"), 1)

    def test_mask_accuracy_100_percent(self):
        records = [{"content": "联系电话 13812345678 邮箱 a@b.com"}]
        masked, report = mask(records, sample_limit=10)
        hits = sum(report.mask_hits.values())
        masked_count = sum(report.masked_count.values())
        self.assertEqual(hits, masked_count)  # 命中数 == 脱敏数 == 100%
        self.assertGreater(hits, 0)

    def test_report_samples_recorded(self):
        records = [{"content": "电话 13812345678"}]
        _, report = mask(records)
        self.assertTrue(report.samples)
        self.assertEqual(report.samples[0]["before"], "13812345678")


if __name__ == "__main__":
    unittest.main()