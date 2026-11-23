# -*- coding: utf-8 -*-
"""PR4 回归测试：课程过滤防误学全课与失败/未开放章节汇总."""
import os
import sys
import unittest
from unittest.mock import Mock, patch

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

    def test_empty_remote_course_list_raises_input_format_error(self):
        for course_list in (None, ["all"], ["1001"]):
            with self.subTest(course_list=course_list), self.assertRaises(InputFormatError):
                main.filter_courses([], course_list)

    def test_interactive_reprompts_on_invalid_id_then_matches(self):
        with patch("builtins.print"), \
             patch("builtins.input", side_effect=["9999", " 1001 "]) as mock_input:
            selected = main.filter_courses(self.all_courses, None)

        self.assertEqual(mock_input.call_count, 2)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["courseId"], "1001")

    def test_interactive_empty_input_raises_input_format_error(self):
        for raw in ("", "   ", " , , "):
            with self.subTest(raw=raw), \
                 patch("builtins.print"), \
                 patch("builtins.input", return_value=raw):
                with self.assertRaisesRegex(InputFormatError, "all"):
                    main.filter_courses(self.all_courses, None)

    def test_interactive_all_keyword_selects_all_courses_and_dedups(self):
        courses_with_dup = self.all_courses + [self.all_courses[0]]
        with patch("builtins.print"), patch("builtins.input", return_value="all"):
            selected = main.filter_courses(courses_with_dup, None)
        self.assertEqual(selected, self.all_courses)

    def test_config_all_keyword_selects_all_courses_and_dedups(self):
        courses_with_dup = self.all_courses + [self.all_courses[0]]
        self.assertEqual(main.filter_courses(courses_with_dup, "all"), self.all_courses)
        self.assertEqual(main.filter_courses(courses_with_dup, [" all "]), self.all_courses)

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

    def test_not_open_continue_records_not_open_task(self):
        task = main.ChapterTask(
            index=0,
            point={"title": "未开放章节", "has_finished": False},
            course={"title": "测试课程"},
        )
        config = {
            "speed": 1.0,
            "jobs": 1,
            "notopen_action": "continue",
            "retry_interval": 0.01,
        }
        processor = main.JobProcessor(
            _DummyChaoxing({"jobs": [], "job_info": {"notOpen": True}}),
            [task],
            config,
        )
        failed_tasks, not_open_tasks = processor.run()

        self.assertEqual(task.tries, 0)
        self.assertEqual(failed_tasks, [])
        self.assertEqual(not_open_tasks, [task])

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

    def _run_main_with(self, points, chapter_results, *, notopen_action="retry", add_learning_count=False):
        course = {"courseId": "1001", "clazzId": "c1", "cpi": "3", "title": "测试课程"}
        common_config = {
            "jobs": 1,
            "speed": 1.0,
            "notopen_action": notopen_action,
            "retry_interval": 0.01,
            "course_list": ["1001"],
            "add_learning_count": add_learning_count,
        }
        mock_cx = Mock()
        mock_cx.login.return_value = {"status": True}
        mock_cx.get_course_list.return_value = [course]
        mock_cx.get_course_point.return_value = {"points": points}

        mock_notifier = Mock()
        mock_factory = Mock()
        mock_factory.get_notification_from_config.return_value = mock_notifier

        with patch("main.init_config", return_value=(common_config, {}, {}, None)), \
             patch("main.init_chaoxing", return_value=mock_cx), \
             patch("main.Notification", return_value=mock_factory), \
             patch("main.process_chapter", side_effect=chapter_results), \
             patch("main.increase_learning_count_for_course") as mock_inc:
            code = main.main()

        return code, mock_notifier, mock_inc

    def test_main_returns_nonzero_and_does_not_report_completion_on_failed_or_not_open(self):
        point = [{"title": "第一章", "has_finished": False}]
        for case, kwargs in (
            ("notopen_continue", {"chapter_results": [main.ChapterResult.NOT_OPEN], "notopen_action": "continue"}),
            ("retry_exhausted", {"chapter_results": [main.ChapterResult.ERROR] * 5, "notopen_action": "retry"}),
        ):
            with self.subTest(case=case):
                code, notifier, mock_inc = self._run_main_with(point, add_learning_count=True, **kwargs)
                self.assertEqual(code, 1)
                msg = notifier.send.call_args.args[0]
                self.assertNotIn("所有课程学习任务已完成", msg)
                self.assertIn("课程任务结束", msg)
                mock_inc.assert_not_called()

    def test_main_returns_nonzero_when_no_chapter_tasks(self):
        code, notifier, mock_inc = self._run_main_with([], [])
        self.assertEqual(code, 1)
        msg = notifier.send.call_args.args[0]
        self.assertNotIn("所有课程学习任务已完成", msg)
        self.assertIn("未获取到可学习的章节任务", msg)
        mock_inc.assert_not_called()

    def test_main_returns_zero_when_all_tasks_succeed(self):
        point = [{"title": "第一章", "has_finished": False}]
        code, notifier, _ = self._run_main_with(point, [main.ChapterResult.SUCCESS])
        self.assertEqual(code, 0)
        self.assertIn("所有课程学习任务已完成", notifier.send.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
