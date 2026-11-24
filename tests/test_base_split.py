# -*- coding: utf-8 -*-
"""PR8 回归测试：api.base 拆分为 api.client 子包、兼容层及 study_work 流程拆解."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import api.base as base_compat  # noqa: E402
import api.client as client_pkg  # noqa: E402
from api.base import Chaoxing, StudyResult  # noqa: E402
from api.tiku.base import DummyTiku, Tiku  # noqa: E402


class _FakeTiku(Tiku):
    def __init__(self, answers_map=None, submit_params="", cover_rate=0.8):
        super().__init__()
        self.DISABLE = False
        self.COVER_RATE = cover_rate
        self._submit_params = submit_params
        self._answers_map = answers_map or {}
        self.feedback_calls = []

    def get_submit_params(self):
        return self._submit_params

    def set_work_feedback(self, feedback):
        self.feedback_calls.append(list(feedback))

    def query_all(self, q_list, query_delay=0):
        return [self._answers_map.get(q["id"]) for q in q_list]

    def _query(self, q_info: dict):
        return None


def _make_response(status_code=200, text="", json_data=None):
    resp = requests.Response()
    resp.status_code = status_code
    if json_data is not None:
        resp._content = json.dumps(json_data, ensure_ascii=False).encode("utf-8")
    else:
        resp._content = text.encode("utf-8")
    resp.encoding = "utf-8"
    return resp


def _make_questions_payload():
    return {
        "workId": "900",
        "workAnswerId": "901",
        "cpi": "777",
        "answerwqbid": "101,102,",
        "questions": [
            {
                "id": "101",
                "title": "第一题",
                "options": "A. 正确选项\nB. 错误选项",
                "type": "single",
                "answerField": {
                    "answer101": "",
                    "answertype101": "0",
                },
            },
            {
                "id": "102",
                "title": "第二题",
                "options": "A. 甲\nB. 乙",
                "type": "single",
                "answerField": {
                    "answer102": "",
                    "answertype102": "0",
                },
            },
        ],
    }


class BaseSplitTestCase(unittest.TestCase):
    _COURSE = {"courseId": "1001", "clazzId": "2002", "cpi": "777"}
    _JOB = {"jobid": "work-900", "enc": "enc-xyz"}
    _JOB_INFO = {"knowledgeid": "3003", "ktoken": "kt-1", "cpi": "777"}

    def test_base_compat_reexports_identical_objects(self):
        compat_lines = (ROOT / "api" / "base.py").read_text(encoding="utf-8").splitlines()
        self.assertLess(len(compat_lines), 60)

        expected_symbols = [
            "Chaoxing",
            "SessionManager",
            "Account",
            "RateLimiter",
            "StudyResult",
            "SignType",
            "ActivityStatus",
            "ActivityType",
            "get_timestamp",
            "multi_cut",
            "clean_res",
            "normalize_text",
            "get_option_text",
            "best_option_by_similarity",
            "is_subsequence",
            "random_answer",
            "_parse_work_record_list",
            "_parse_work_record_detail",
            "normalize_answer_text",
            "_JUDGE_TRUE_SET",
            "_JUDGE_FALSE_SET",
        ]
        self.assertEqual(set(base_compat.__all__), set(expected_symbols))
        self.assertEqual(set(client_pkg.__all__), set(expected_symbols))
        for name in expected_symbols:
            self.assertIs(getattr(base_compat, name), getattr(client_pkg, name))

        for method_name in (
            "login",
            "get_name",
            "get_fid",
            "get_uid",
            "get_course_list",
            "get_activity_list",
            "pre_sign",
            "sign_in_normal",
            "get_course_point",
            "get_job_list",
            "get_enc",
            "video_progress_log",
            "study_video",
            "study_document",
            "study_read",
            "study_emptypage",
            "increase_chapter_learning_count",
            "study_work",
            "_check_work_result",
            "_resolve_work_redo_retries",
            "_is_manual_tiku",
            "_fetch_work_questions",
            "_match_question_answer",
            "_query_and_fill_work_answers",
            "_build_work_submit_payload",
            "_submit_work_form",
            "_evaluate_work_submission",
        ):
            self.assertTrue(callable(getattr(Chaoxing, method_name)), msg=method_name)

    def test_direct_submodule_imports_have_no_circular_import(self):
        for mod_name in (
            "api.client.models",
            "api.client.session",
            "api.client.login",
            "api.client.sign",
            "api.client.course",
            "api.client.video",
            "api.client.work_parser",
            "api.client.work",
            "api.client.chaoxing",
            "api.client",
            "api.base",
        ):
            with self.subTest(module=mod_name):
                proc = subprocess.run(
                    [sys.executable, "-c", f"import {mod_name}"],
                    cwd=str(ROOT),
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(proc.returncode, 0, msg=proc.stderr)

    def test_study_work_returns_success_when_tiku_none_or_disabled(self):
        cx_none = Chaoxing(tiku=None)
        self.assertEqual(cx_none.study_work(self._COURSE, self._JOB, self._JOB_INFO), StudyResult.SUCCESS)

        dummy = DummyTiku()
        self.assertTrue(dummy.DISABLE)
        cx_disabled = Chaoxing(tiku=dummy)
        self.assertEqual(cx_disabled.study_work(self._COURSE, self._JOB, self._JOB_INFO), StudyResult.SUCCESS)

    def test_study_work_permission_error_skips_without_retry(self):
        fake_session = Mock()
        fake_session.get.return_value = _make_response(200, text="<html>教师未创建完成该测验</html>")
        cx = Chaoxing(tiku=_FakeTiku())

        with patch("api.client.work.SessionManager.get_session", return_value=fake_session):
            res = cx.study_work(self._COURSE, self._JOB, self._JOB_INFO)

        self.assertEqual(res, StudyResult.SUCCESS)
        self.assertEqual(fake_session.get.call_count, 1)

    def test_study_work_low_cover_rate_builds_save_payload_and_skips_check(self):
        fake_session = Mock()
        fake_session.get.return_value = _make_response(200, text="<html>questions</html>")
        fake_session.post.return_value = _make_response(200, json_data={"status": True, "msg": "保存成功"})

        # 第 1 题命中、第 2 题未命中 -> 覆盖率 50% < 80%，触发保存模式 pyFlag="1"
        tiku = _FakeTiku(answers_map={"101": "正确选项", "102": None}, cover_rate=0.8)
        cx = Chaoxing(tiku=tiku)

        with patch("api.client.work.SessionManager.get_session", return_value=fake_session), \
             patch("api.client.work.decode_questions_info", return_value=_make_questions_payload()), \
             patch.object(cx, "_check_work_result") as mock_check:
            res = cx.study_work(self._COURSE, self._JOB, self._JOB_INFO)

        self.assertEqual(res, StudyResult.SUCCESS)
        mock_check.assert_not_called()
        fake_session.post.assert_called_once()
        posted_data = fake_session.post.call_args.kwargs["data"]
        self.assertEqual(posted_data["pyFlag"], "1")
        self.assertEqual(posted_data["answer101"], "A")
        self.assertEqual(posted_data["answer102"], "")
        self.assertNotIn("questions", posted_data)

    def test_study_work_submit_and_redo_flow_with_feedback(self):
        fake_session = Mock()
        fake_session.get.return_value = _make_response(200, text="<html>questions</html>")
        fake_session.post.return_value = _make_response(200, json_data={"status": True, "msg": "提交成功"})

        tiku = _FakeTiku(answers_map={"101": "正确选项", "102": "乙"}, cover_rate=0.8)
        cx = Chaoxing(tiku=tiku, work_redo_enabled=True, work_max_retries=1)

        check_results = [
            {
                "all_correct": False,
                "feedback": ["- 题目：第二题\n  正确答案：A. 甲"],
                "score": 50.0,
                "times": 1,
                "unknown": 0,
            },
            {
                "all_correct": True,
                "feedback": [],
                "score": 100.0,
                "times": 2,
                "unknown": 0,
            },
        ]

        with patch("api.client.work.SessionManager.get_session", return_value=fake_session), \
             patch("api.client.work.decode_questions_info", side_effect=[_make_questions_payload(), _make_questions_payload()]), \
             patch.object(cx, "_check_work_result", side_effect=check_results), \
             patch("api.client.work.time.sleep") as mock_sleep:
            res = cx.study_work(self._COURSE, self._JOB, self._JOB_INFO)

        self.assertEqual(res, StudyResult.SUCCESS)
        self.assertEqual(cx.rollback_times, 1)
        self.assertEqual(fake_session.post.call_count, 2)
        self.assertEqual(len(tiku.feedback_calls), 1)
        self.assertIn("第二题", tiku.feedback_calls[0][0])
        mock_sleep.assert_called_once_with(2)

    def test_study_work_submit_failure_returns_error(self):
        fake_session = Mock()
        fake_session.get.return_value = _make_response(200, text="<html>questions</html>")
        fake_session.post.return_value = _make_response(200, json_data={"status": False, "msg": "禁止提交"})

        tiku = _FakeTiku(answers_map={"101": "正确选项", "102": "甲"}, cover_rate=0.5)
        cx = Chaoxing(tiku=tiku)

        with patch("api.client.work.SessionManager.get_session", return_value=fake_session), \
             patch("api.client.work.decode_questions_info", return_value=_make_questions_payload()):
            res = cx.study_work(self._COURSE, self._JOB, self._JOB_INFO)

        self.assertEqual(res, StudyResult.ERROR)

    def test_evaluate_work_submission_full_score_unknown_and_none_branches(self):
        cx = Chaoxing(tiku=_FakeTiku())
        payload = {"pyFlag": ""}

        # 无法获取成绩详情
        with patch.object(cx, "_check_work_result", return_value=None):
            res, fb, score = cx._evaluate_work_submission(Mock(), self._COURSE, self._JOB, self._JOB_INFO, payload, 0, 1, 2)
        self.assertEqual((res, fb, score), (StudyResult.SUCCESS, None, None))

        # 满分但含未解析题目
        with patch.object(cx, "_check_work_result", return_value={"all_correct": False, "score": 100.0, "unknown": 1, "feedback": []}):
            res, fb, score = cx._evaluate_work_submission(Mock(), self._COURSE, self._JOB, self._JOB_INFO, payload, 0, 1, 2)
        self.assertEqual(res, StudyResult.SUCCESS)
        self.assertIsNone(fb)
        self.assertEqual(score, 100.0)

        # 非满分且含未解析题目 -> 不触发重做
        with patch.object(cx, "_check_work_result", return_value={"all_correct": False, "score": 60.0, "unknown": 1, "feedback": []}):
            res, fb, score = cx._evaluate_work_submission(Mock(), self._COURSE, self._JOB, self._JOB_INFO, payload, 0, 2, 2)
        self.assertEqual(res, StudyResult.SUCCESS)
        self.assertIsNone(fb)
        self.assertEqual(score, 60.0)


if __name__ == "__main__":
    unittest.main()
