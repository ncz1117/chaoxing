# -*- coding: utf-8 -*-
"""SessionManager 每线程会话复用、隔离与 Cookie 同步删除回归测试."""
import os
import sys
import threading
import unittest
from unittest.mock import patch

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.base import SessionManager  # noqa: E402


class SessionManagerTestCase(unittest.TestCase):
    def setUp(self):
        self.cookies = {"session": "old-val", "stale": "to-be-removed"}
        self.cookie_patch = patch("api.base.use_cookies", side_effect=lambda: dict(self.cookies))
        self.cookie_patch.start()
        SessionManager.close_session()
        SessionManager.update_cookies()

    def tearDown(self):
        SessionManager.close_session()
        SessionManager.update_cookies()
        self.cookie_patch.stop()

    def test_same_thread_reuses_session(self):
        s1 = SessionManager.get_session()
        s2 = SessionManager.get_session()
        self.assertIs(s1, s2)
        self.assertEqual(s1.cookies.get("session"), "old-val")

    def test_different_threads_get_distinct_sessions_and_reuse_own(self):
        main_session = SessionManager.get_session()
        barrier = threading.Barrier(4)
        results = []
        lock = threading.Lock()

        def worker():
            try:
                barrier.wait(timeout=3)
                s1 = SessionManager.get_session()
                s2 = SessionManager.get_session()
                with lock:
                    results.append((s1, s1 is s2))
            finally:
                SessionManager.close_session()

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
            self.assertFalse(t.is_alive())

        self.assertEqual(len(results), 4)
        worker_sessions = [item[0] for item in results]
        self.assertTrue(all(reused for _, reused in results))
        self.assertTrue(all(ws is not main_session for ws in worker_sessions))
        self.assertEqual(len({id(ws) for ws in worker_sessions}), 4)

    def test_update_cookies_syncs_changes_and_clears_removed_cookies(self):
        main_session = SessionManager.get_session()
        self.assertEqual(main_session.cookies.get("stale"), "to-be-removed")

        ready = threading.Event()
        refresh = threading.Event()
        worker_state = {}

        def send(session, prepared, **kwargs):
            worker_state["sent_cookie"] = prepared.headers.get("Cookie", "")
            resp = requests.Response()
            resp.status_code = 200
            resp._content = b"{}"
            return resp

        def worker():
            try:
                s = SessionManager.get_session()
                worker_state["before_stale"] = s.cookies.get("stale")
                ready.set()
                if not refresh.wait(3):
                    raise RuntimeError("同步等待超时")
                # 即使直接复用已持有的 s 引用发请求，也应同步清除被移除的 cookie
                s.get("https://mooc1.chaoxing.com/fixture")
                worker_state["after_session"] = s.cookies.get("session")
                worker_state["after_stale"] = s.cookies.get("stale")
                worker_state["after_added"] = s.cookies.get("added")
            except Exception as exc:
                worker_state["error"] = exc
            finally:
                SessionManager.close_session()

        with patch.object(requests.Session, "send", autospec=True, side_effect=send):
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            try:
                self.assertTrue(ready.wait(3))
                self.assertEqual(worker_state["before_stale"], "to-be-removed")
                self.cookies = {"session": "new-val", "added": "extra"}
                SessionManager.update_cookies()
                # 当前主线程持有的旧引用应已同步清理与更新
                self.assertEqual(main_session.cookies.get("session"), "new-val")
                self.assertEqual(main_session.cookies.get("added"), "extra")
                self.assertIsNone(main_session.cookies.get("stale"))
            finally:
                refresh.set()
                thread.join(5)

        self.assertFalse(thread.is_alive())
        self.assertNotIn("error", worker_state)
        self.assertEqual(worker_state["after_session"], "new-val")
        self.assertEqual(worker_state["after_added"], "extra")
        self.assertIsNone(worker_state["after_stale"])
        self.assertIn("session=new-val", worker_state["sent_cookie"])
        self.assertNotIn("stale=", worker_state["sent_cookie"])

    def test_close_session_releases_and_creates_fresh_session(self):
        first = SessionManager.get_session()
        with patch.object(first, "close") as mock_close:
            SessionManager.close_session()
        mock_close.assert_called_once()
        second = SessionManager.get_session()
        self.assertIsNot(first, second)


if __name__ == "__main__":
    unittest.main()
