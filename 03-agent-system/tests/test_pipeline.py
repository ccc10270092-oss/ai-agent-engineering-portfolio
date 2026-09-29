"""数据管道测试：清洗 / 去重 / 会话切分（BR-03.x）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_pipeline.cleaner import clean  # noqa: E402
from data_pipeline.dedupe import dedupe  # noqa: E402
from data_pipeline.masker import run_pipeline  # noqa: E402
from data_pipeline.session_split import split_sessions  # noqa: E402


class TestCleaner(unittest.TestCase):
    def test_drops_empty_records(self):
        records = [{"content": "   "}, {"content": "有效内容"}]
        self.assertEqual(len(clean(records)), 1)

    def test_normalizes_whitespace(self):
        records = [{"content": "你好\n\n  世界"}]
        self.assertEqual(clean(records)[0]["content"], "你好 世界")

    def test_drops_nan_records(self):
        """pandas 读 CSV 空单元格得到 float nan（不是 None），也应按空记录丢弃。"""
        records = [{"content": float("nan")}, {"content": "有效内容"}]
        self.assertEqual(len(clean(records)), 1)


class TestDedupe(unittest.TestCase):
    def test_removes_duplicates(self):
        records = [
            {"content": "重复内容"},
            {"content": "重复内容"},
            {"content": "另一条"},
        ]
        self.assertEqual(len(dedupe(records)), 2)


class TestSessionSplit(unittest.TestCase):
    def test_split_by_id_isolates_sessions(self):
        records = [
            {"session_id": "s1", "content": "a"},
            {"session_id": "s2", "content": "b"},
            {"session_id": "s1", "content": "c"},
        ]
        sessions = split_sessions(records)
        ids = {s["session_id"] for s in sessions}
        self.assertEqual(ids, {"s1", "s2"})
        self.assertEqual(len(sessions), 2)

    def test_split_by_time_gap(self):
        records = [
            {"timestamp": "2025-09-01 10:00:00", "content": "a"},
            {"timestamp": "2025-09-01 10:05:00", "content": "b"},
            {"timestamp": "2025-09-01 11:00:00", "content": "c"},
        ]
        sessions = split_sessions(records, time_field="timestamp", time_gap_minutes=30)
        self.assertEqual(len(sessions), 2)  # 前两条同会话，第三条新会话


class TestRunPipeline(unittest.TestCase):
    def test_stage_stats_funnel(self):
        """报告附带各阶段计数：输入 → 清洗丢弃 → 去重删除 → 输出。"""
        records = [
            {"session_id": "s1", "content": "手机号 13812345678"},
            {"session_id": "s1", "content": "手机号 13812345678"},  # 重复
            {"content": "   "},  # 空记录
        ]
        masked, report = run_pipeline(records)
        self.assertEqual(report.stage_stats["input"], 3)
        self.assertEqual(report.stage_stats["clean_dropped"], 1)
        self.assertEqual(report.stage_stats["dedupe_removed"], 1)
        self.assertEqual(report.stage_stats["output"], 1)
        self.assertEqual(report.mask_hits.get("phone"), 1)


if __name__ == "__main__":
    unittest.main()