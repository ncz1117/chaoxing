# -*- coding: utf-8 -*-
"""PR4 回归测试：课程过滤防误学全课与失败/未开放章节汇总."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402
from api.exceptions import InputFormatError  # noqa: E402


class _DummyRateLimiter:
    def limit_rate(self, *args, **kwargs):
        return None


class _DummyChaoxing:
    def __init__(self, job_info):
        self.job_info = job_info
        self.rate_limiter = _DummyRateLimiter()

    def get_job_list(self, course, point):
        return self.job_info["jobs"], self.job_info["job_info"]


class CourseFilterAndSummaryTestCase(unittest.TestCase):
    def setUp(self):
        main.logger.remove()
        self.all_courses = [
            {"courseId": "1001", "clazzId": "c1", "title": "高数"},
            {"courseId": "1002", "clazzId": "c2", "title": "线代"},
        ]

    def test_interactive_reprompts_on_invalid_id_then_matches(self):
        with patch("builtins.print"), \
             patch("builtins.input", side_effect=["9999", " 1001 "]) as mock_input:
            selected = main.filter_courses(self.all_courses, None)

        self.assertEqual(mock_input.call_count, 2)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["courseId"], "1001")

    def test_interactive_empty_input_selects_all_courses(self):
        with patch("builtins.print"), patch("builtins.input", return_value=""):
            selected = main.filter_courses(self.all_courses, None)
        self.assertEqual(len(selected), 2)

    def test_interactive_all_keyword_selects_all_courses(self):
        with patch("builtins.print"), patch("builtins.input", return_value="all"):
            selected = main.filter_courses(self.all_courses, None)
        self.assertEqual(len(selected), 2)

    def test_config_all_unmatched_raises_input_format_error(self):
        with self.assertRaises(InputFormatError):
            main.filter_courses(self.all_courses, ["9999", "8888"])

    def test_config_partial_match_warns_and_returns_matched(self):
        warnings = []
        with patch("main.logger.warning", side_effect=lambda msg, *a, **kw: warnings.append(str(msg))):
            selected = main.filter_courses(self.all_courses, ["1002", "9999"])
        self.assertEqual([c["courseId"] for c in selected], ["1002"])
        self.assertTrue(any("9999" in w for w in warnings))

    def test_job_processor_records_not_open_tasks_and_returns_summary(self):
        task = main.ChapterTask(
            index=0,
            point={"title": "未开放章节", "has_finished": False},
            course={"title": "测试课程"},
        )
        config = {
            "speed": 1.0,
            "jobs": 1,
            "notopen_action": "retry",
            "retry_interval": 0.01,
        }
        processor = main.JobProcessor(
            _DummyChaoxing({"jobs": [], "job_info": {"notOpen": True}}),
            [task],
            config,
        )
        processor.max_tries = 2
        failed_tasks, not_open_tasks = processor.run()

        self.assertEqual(failed_tasks, [])
        self.assertEqual(not_open_tasks, [task])
        self.assertEqual(processor.not_open_tasks, [task])

    def test_job_processor_records_failed_tasks_and_returns_summary(self):
        task = main.ChapterTask(
            index=0,
            point={"title": "异常章节", "has_finished": False},
            course={"title": "测试课程"},
        )
        config = {
            "speed": 1.0,
            "jobs": 1,
            "notopen_action": "retry",
            "retry_interval": 0.01,
        }
        processor = main.JobProcessor(
            _DummyChaoxing({"jobs": [{"type": "unknown"}], "job_info": {}}),
            [task],
            config,
        )
        processor.max_tries = 2
        failed_tasks, not_open_tasks = processor.run()

        self.assertEqual(failed_tasks, [task])
        self.assertEqual(not_open_tasks, [])


if __name__ == "__main__":
    unittest.main()
