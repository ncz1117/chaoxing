# -*- coding: utf-8 -*-
"""PR3 安全加固回归测试：TLS 证书校验开关与 Cookie 日志脱敏."""
import os
import sys
import unittest
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402
from api.answer import Tiku, TikuAdapter, TikuFallback, TikuYanxi  # noqa: E402
from api.base import Chaoxing  # noqa: E402


class _DummyProvider(Tiku):
    def _query(self, q_info: dict):
        return None


class SecurityHardeningTestCase(unittest.TestCase):
    def _base_conf(self, **extra):
        conf = {
            "submit": "false",
            "cover_rate": "0.8",
            "true_list": "正确,对",
            "false_list": "错误,错",
            "tokens": "tok1",
            "url": "https://example.com/query",
        }
        conf.update(extra)
        return conf

    def test_tiku_ssl_verify_defaults_to_true(self):
        provider = _DummyProvider()
        self.assertTrue(provider.ssl_verify)
        provider.config_set(self._base_conf())
        provider.init_tiku()
        self.assertTrue(provider.ssl_verify)

    def test_tiku_ssl_verify_can_be_disabled(self):
        for val in ("false", "False", "0", "no", "off"):
            provider = _DummyProvider()
            provider.config_set(self._base_conf(ssl_verify=val))
            provider.init_tiku()
            self.assertFalse(provider.ssl_verify, msg=f"ssl_verify={val} 应解析为 False")

    def test_tiku_fallback_propagates_ssl_verify(self):
        p1 = TikuYanxi()
        p2 = TikuAdapter()
        fallback = TikuFallback([p1, p2])
        fallback.config_set(self._base_conf(ssl_verify="false"))
        fallback.init_tiku()
        self.assertFalse(fallback.ssl_verify)
        self.assertFalse(p1.ssl_verify)
        self.assertFalse(p2.ssl_verify)

    def test_cookie_login_does_not_log_cookie_values(self):
        fake_session = requests.Session()
        secret_val = "SUPER_SECRET_COOKIE_VALUE_12345"
        fake_session.cookies.set("secret_cookie_name", secret_val)
        debug_messages = []
        with patch("api.base.SessionManager.update_cookies"), \
             patch("api.base.SessionManager.get_session", return_value=fake_session), \
             patch.object(Chaoxing, "_validate_cookie_session", return_value=False), \
             patch("api.base.logger.debug", side_effect=lambda msg, *a, **kw: debug_messages.append(str(msg) + " " + str(a))):
            cx = Chaoxing()
            cx.login(login_with_cookies=True)

        joined = "\n".join(debug_messages)
        self.assertIn("secret_cookie_name", joined)
        self.assertNotIn(secret_val, joined)

    def test_error_notification_does_not_leak_exception_text(self):
        mock_notifier = Mock()
        mock_factory = Mock()
        mock_factory.get_notification_from_config.return_value = mock_notifier
        mock_cx = Mock()
        mock_cx.login.side_effect = RuntimeError("token=SECRET_TOKEN_999")

        with patch("main.init_config", return_value=({}, {}, {}, None)), \
             patch("main.init_chaoxing", return_value=mock_cx), \
             patch("main.Notification", return_value=mock_factory), \
             patch("main.logger"):
            with self.assertRaises(RuntimeError):
                main.main()

        mock_notifier.send.assert_called_once()
        sent = mock_notifier.send.call_args.args[0]
        self.assertIn("RuntimeError", sent)
        self.assertIn("请查看 chaoxing.log 了解详情", sent)
        self.assertNotIn("SECRET_TOKEN_999", sent)


if __name__ == "__main__":
    unittest.main()
