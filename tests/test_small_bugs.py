# -*- coding: utf-8 -*-
"""PR2 回归测试：ChapterResult 值类型、log_error 返回值与元信息、login 响应校验."""
import os
import sys
import unittest
from unittest.mock import patch

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402
from api.base import Account, Chaoxing  # noqa: E402


class SmallBugsTestCase(unittest.TestCase):
    def test_chapter_result_values_are_int(self):
        for member in main.ChapterResult:
            self.assertIsInstance(member.value, int)
            self.assertNotIsInstance(member.value, tuple)

    def test_log_error_preserves_return_value_and_name(self):
        @main.log_error
        def sample_worker(x, y=1):
            """sample docstring."""
            return x + y

        self.assertEqual(sample_worker.__name__, "sample_worker")
        self.assertEqual(sample_worker(2, y=3), 5)

    def _make_chaoxing(self):
        return Chaoxing(account=Account("13800000000", "secret123456"))

    def test_login_handles_http_500(self):
        resp = requests.Response()
        resp.status_code = 500
        resp._content = b"Internal Server Error"
        with patch("api.base.requests.Session.post", return_value=resp):
            result = self._make_chaoxing().login(login_with_cookies=False)
        self.assertIs(result["status"], False)
        self.assertTrue(result["msg"])

    def test_login_handles_non_json_response(self):
        resp = requests.Response()
        resp.status_code = 200
        resp._content = b"<html>not json</html>"
        with patch("api.base.requests.Session.post", return_value=resp):
            result = self._make_chaoxing().login(login_with_cookies=False)
        self.assertIs(result["status"], False)
        self.assertTrue(result["msg"])

    def test_login_handles_failure_without_msg2(self):
        resp = requests.Response()
        resp.status_code = 200
        resp._content = b'{"status": false}'
        with patch("api.base.requests.Session.post", return_value=resp):
            result = self._make_chaoxing().login(login_with_cookies=False)
        self.assertIs(result["status"], False)
        self.assertEqual(result["msg"], "登录失败, 未知原因")


if __name__ == "__main__":
    unittest.main()
