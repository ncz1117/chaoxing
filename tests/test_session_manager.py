# -*- coding: utf-8 -*-
"""SessionManager 单例与会话复用回归测试."""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.base import SessionManager  # noqa: E402


class SessionManagerTestCase(unittest.TestCase):
    def tearDown(self):
        session = SessionManager.get_session()
        if "probe" in session.cookies:
            del session.cookies["probe"]

    def test_get_session_returns_same_instance(self):
        s1 = SessionManager.get_session()
        s2 = SessionManager.get_session()
        self.assertIs(s1, s2)

    def test_session_cookies_persist_across_calls(self):
        s1 = SessionManager.get_session()
        s1.cookies.set("probe", "1")
        s2 = SessionManager.get_session()
        self.assertEqual(s2.cookies.get("probe"), "1")

    def test_concurrent_get_session_returns_same_id(self):
        SessionManager._instance = None
        num_threads = 20
        barrier = threading.Barrier(num_threads)
        session_ids = []
        lock = threading.Lock()

        def worker():
            barrier.wait()
            s = SessionManager.get_session()
            with lock:
                session_ids.append(id(s))

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
            self.assertFalse(t.is_alive())

        self.assertEqual(len(session_ids), num_threads)
        self.assertEqual(len(set(session_ids)), 1)


if __name__ == "__main__":
    unittest.main()
