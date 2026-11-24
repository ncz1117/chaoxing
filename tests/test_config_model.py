# -*- coding: utf-8 -*-
"""PR9 回归测试：dataclass 配置模型解析、校验、默认值与向下兼容."""
from argparse import Namespace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from api.config import (  # noqa: E402
    AppConfig,
    CommonConfig,
    NotificationConfig,
    TikuConfig,
    build_app_config_from_args,
    load_app_config,
)
from api.exceptions import InputFormatError  # noqa: E402
from api.notification import NotificationFactory, ServerChan  # noqa: E402
from api.process import increase_learning_count_for_course  # noqa: E402
from api.tiku.base import DummyTiku, Tiku  # noqa: E402
from api.tiku.like import TikuLike  # noqa: E402
from api.tiku.yanxi import TikuYanxi  # noqa: E402


class ConfigModelTestCase(unittest.TestCase):
    def test_load_config_template_ini_succeeds_with_typed_fields(self):
        app_cfg = load_app_config(ROOT / "config_template.ini")
        self.assertIsInstance(app_cfg, AppConfig)
        self.assertIsInstance(app_cfg.common, CommonConfig)
        self.assertIsInstance(app_cfg.tiku, TikuConfig)
        self.assertIsInstance(app_cfg.notification, NotificationConfig)

        self.assertIs(app_cfg.common.use_cookies, False)
        self.assertEqual(app_cfg.common.username, "xxx")
        self.assertEqual(app_cfg.common.course_list, ["xxx", "xxx", "xxx"])
        self.assertEqual(app_cfg.common.speed, 1.0)
        self.assertEqual(app_cfg.common.jobs, 4)
        self.assertEqual(app_cfg.common.notopen_action, "retry")
        self.assertEqual(app_cfg.common.retry_interval, 1.0)
        self.assertIs(app_cfg.common.work_redo_enabled, False)
        self.assertEqual(app_cfg.common.work_max_retries, 3)
        self.assertIs(app_cfg.common.add_learning_count, False)
        self.assertEqual(app_cfg.common.target_count, 100)

        self.assertEqual(app_cfg.tiku.provider, "TikuYanxi")
        self.assertIs(app_cfg.tiku.ssl_verify, True)
        self.assertIs(app_cfg.tiku.submit, False)
        self.assertAlmostEqual(app_cfg.tiku.cover_rate, 0.9)
        self.assertEqual(app_cfg.tiku.delay, 1.0)
        self.assertIs(app_cfg.tiku.likeapi_search, False)
        self.assertIs(app_cfg.tiku.likeapi_vision, True)
        self.assertEqual(app_cfg.tiku.manual_mode_default, "batch")
        self.assertEqual(app_cfg.tiku.manual_mode_separator, ";")

        self.assertEqual(app_cfg.notification.provider, "ServerChan")
        self.assertEqual(app_cfg.notification.url, "")
        self.assertEqual(app_cfg.notification.tg_chat_id, "XXXXXX")

    def test_common_config_defaults_clamping_and_validation(self):
        default_cfg = CommonConfig()
        self.assertEqual((default_cfg.speed, default_cfg.jobs, default_cfg.notopen_action), (1.0, 4, "retry"))

        clamped_high = CommonConfig(speed=5.0)
        clamped_low = CommonConfig(speed=0.2)
        self.assertEqual(clamped_high.speed, 2.0)
        self.assertEqual(clamped_low.speed, 1.0)

        mapped = CommonConfig.from_mapping(
            {
                "username": " 13800000000 ",
                "speed": "1.5",
                "jobs": "2",
                "notopen_action": "CONTINUE",
                "retry_interval": "0",
                "custom_flag": "yes",
            }
        )
        self.assertEqual(mapped.username, "13800000000")
        self.assertEqual(mapped.speed, 1.5)
        self.assertEqual(mapped["jobs"], 2)
        self.assertEqual(mapped.notopen_action, "continue")
        self.assertEqual(mapped.retry_interval, 0.0)
        self.assertEqual(mapped["custom_flag"], "yes")
        self.assertEqual(mapped.get("custom_flag"), "yes")
        self.assertIn("speed", mapped)
        self.assertIn("custom_flag", mapped)

        invalid_cases = [
            {"speed": "abc"},
            {"speed": "nan"},
            {"speed": True},
            {"jobs": 0},
            {"jobs": -1},
            {"jobs": True},
            {"jobs": 1.5},
            {"work_max_retries": 0},
            {"target_count": 0},
            {"retry_interval": -0.5},
            {"notopen_action": "invalid"},
        ]
        for bad in invalid_cases:
            with self.subTest(bad=bad), self.assertRaises(InputFormatError):
                CommonConfig.from_mapping(bad)

    def test_tiku_config_defaults_booleans_validation_and_truthiness(self):
        empty = TikuConfig()
        self.assertFalse(bool(empty))
        self.assertFalse(bool(TikuConfig.from_mapping({})))
        self.assertTrue(bool(TikuConfig.from_mapping({"submit": "false"})))
        self.assertTrue(bool(TikuConfig(provider="TikuYanxi, TikuAdapter")))

        cfg = TikuConfig.from_mapping(
            {
                "provider": " TikuYanxi , TikuLike ",
                "tokens": "tok1,tok2",
                "likeapi_search": "false",
                "likeapi_vision": "true",
                "manual_mode_default": "SINGLE",
                "manual_mode_separator": " ",
            }
        )
        self.assertEqual(cfg.providers, ["TikuYanxi", "TikuLike"])
        self.assertEqual(cfg.manual_mode_default, "single")
        # 保留空格等空白分隔符，不被 strip
        self.assertEqual(cfg.manual_mode_separator, " ")

        like = TikuLike()
        like.config_set(cfg)
        like.load_config()
        self.assertIs(like._search, False)
        self.assertIs(like._vision, True)

        for bad in (
            {"cover_rate": -0.1},
            {"cover_rate": 1.5},
            {"delay": -1},
            {"go_min_interval": -0.1},
            {"go_retry_times": 0},
            {"go_retry_backoff": -0.5},
            {"min_interval_seconds": -1},
            {"manual_mode_default": "invalid"},
        ):
            with self.subTest(bad=bad), self.assertRaises(InputFormatError):
                TikuConfig.from_mapping(bad)

    def test_notification_config_defaults_validation_and_service_compat(self):
        self.assertFalse(bool(NotificationConfig()))
        self.assertFalse(bool(NotificationConfig.from_mapping({})))

        with self.assertRaises(InputFormatError):
            NotificationConfig(provider="ServerChan", url="ftp://example.com/hook")

        cfg = NotificationConfig(provider="ServerChan", url="https://sctapi.ftqq.com/test.send")
        self.assertTrue(bool(cfg))
        service = NotificationFactory.create_service(cfg)
        self.assertIsInstance(service, ServerChan)
        self.assertFalse(service.disabled)
        self.assertEqual(service.url, "https://sctapi.ftqq.com/test.send")

    def test_load_app_config_missing_file_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            load_app_config(ROOT / "not_existing_config_file_12345.ini")

    def test_build_config_from_args_produces_validated_models(self):
        args = Namespace(
            config=None,
            use_cookies=True,
            username="13800000000",
            password="",
            list="1001, 1002",
            speed=3.0,
            jobs=2,
            notopen_action="continue",
            retry_interval=0.0,
            add_learning_count=True,
            target_count=50,
            auto_sign=True,
            verbose=True,
        )
        app_cfg = build_app_config_from_args(args)
        self.assertIs(app_cfg.common.use_cookies, True)
        self.assertEqual(app_cfg.common.course_list, ["1001", "1002"])
        self.assertEqual(app_cfg.common.speed, 2.0)
        self.assertEqual(app_cfg.common.jobs, 2)
        self.assertEqual(app_cfg.common.notopen_action, "continue")
        self.assertEqual(app_cfg.common.retry_interval, 0.0)
        self.assertIs(app_cfg.common.add_learning_count, True)
        self.assertEqual(app_cfg.common.target_count, 50)
        self.assertIs(app_cfg.common.auto_sign, True)
        self.assertIs(app_cfg.common.verbose, True)
        self.assertFalse(bool(app_cfg.tiku))
        self.assertFalse(bool(app_cfg.notification))

    def test_tiku_init_and_init_chaoxing_accept_tiku_config_bools(self):
        provider = TikuYanxi()
        provider.config_set(TikuConfig(provider="TikuYanxi", tokens="t1", submit=True, ssl_verify=False))
        provider.init_tiku()
        self.assertIs(provider.SUBMIT, True)
        self.assertIs(provider.ssl_verify, False)

        common_cfg = CommonConfig(use_cookies=True)
        tiku_cfg = TikuConfig(
            provider="AI",
            endpoint="https://example.com/v1",
            key="sk-test",
            model="gpt-test",
            check_llm_connection=False,
        )
        cx = main.init_chaoxing(common_cfg, tiku_cfg)
        self.assertEqual(cx.tiku.endpoint, "https://example.com/v1")

    def test_job_processor_and_increase_learning_count_accept_both_common_config_and_dict(self):
        cfg_model = CommonConfig(speed=1.5, jobs=2, notopen_action="continue", retry_interval=0.25, target_count=12)
        cfg_dict = {"speed": 1.5, "jobs": 2, "notopen_action": "continue", "retry_interval": 0.25, "target_count": 12}

        p1 = main.JobProcessor(Mock(), [], cfg_model)
        p2 = main.JobProcessor(Mock(), [], cfg_dict)
        self.assertEqual((p1.speed, p1.worker_num, p1.retry_interval), (1.5, 2, 0.25))
        self.assertEqual((p2.speed, p2.worker_num, p2.retry_interval), (1.5, 2, 0.25))
        self.assertEqual(p1.config.notopen_action, "continue")
        self.assertEqual(p2.config.notopen_action, "continue")

        fake_cx = Mock()
        fake_cx.get_course_point.return_value = {"points": [{"id": "1", "title": "c1"}]}
        fake_cx.increase_chapter_learning_count.return_value = main.StudyResult.SUCCESS
        course = {"courseId": "10", "clazzId": "20", "cpi": "30", "title": "测试课程"}

        with patch("api.process.logger"):
            increase_learning_count_for_course(fake_cx, course, cfg_model)
            increase_learning_count_for_course(fake_cx, course, cfg_dict)

        self.assertEqual(fake_cx.increase_chapter_learning_count.call_count, 2)
        for call in fake_cx.increase_chapter_learning_count.call_args_list:
            self.assertEqual(call.args[2], 12)

    def test_tiku_submit_only_enables_for_exact_lowercase_true_or_bool(self):
        for val in ("yes", "1", "True", "TRUE", "on", "y", "false", 1, ""):
            with self.subTest(val=val):
                cfg = TikuConfig.from_mapping({"provider": "TikuYanxi", "tokens": "t1", "submit": val})
                self.assertIs(cfg.submit, False)
                provider = TikuYanxi()
                provider.config_set(cfg)
                provider.init_tiku()
                self.assertIs(provider.SUBMIT, False)
                self.assertEqual(provider.get_submit_params(), "1")

        for val in ("true", True):
            with self.subTest(enabled_val=val):
                cfg = TikuConfig.from_mapping({"provider": "TikuYanxi", "tokens": "t1", "submit": val})
                self.assertIs(cfg.submit, True)
                provider = TikuYanxi()
                provider.config_set(cfg)
                provider.init_tiku()
                self.assertIs(provider.SUBMIT, True)
                self.assertEqual(provider.get_submit_params(), "")

        with tempfile.TemporaryDirectory() as tmp_dir:
            for raw_submit, expected in (("yes", False), ("1", False), ("True", False), ("true", True)):
                with self.subTest(ini_submit=raw_submit):
                    ini_path = Path(tmp_dir) / f"cfg_{raw_submit}.ini"
                    ini_path.write_text(
                        f"[tiku]\nprovider = TikuYanxi\ntokens = t1\nsubmit = {raw_submit}\n",
                        encoding="utf-8",
                    )
                    loaded = load_app_config(ini_path)
                    self.assertIs(loaded.tiku.submit, expected)
                    provider = Tiku.get_tiku_from_config(loaded.tiku, config_path=str(ini_path))
                    provider.init_tiku()
                    self.assertIs(provider.SUBMIT, expected)
                    self.assertEqual(provider.get_submit_params(), "" if expected else "1")

    def test_cli_password_preserves_leading_and_trailing_whitespace(self):
        raw_password = "  sec ret  "
        args = Namespace(
            config=None,
            use_cookies=False,
            username="13800000000",
            password=raw_password,
            list=None,
            speed=1.0,
            jobs=4,
            notopen_action="retry",
            retry_interval=1.0,
            add_learning_count=False,
            target_count=100,
            auto_sign=False,
            verbose=False,
        )
        app_cfg = build_app_config_from_args(args)
        self.assertEqual(app_cfg.common.password, raw_password)

        with patch.object(Tiku, "get_tiku_from_config", return_value=DummyTiku()):
            cx = main.init_chaoxing(app_cfg.common, app_cfg.tiku)
        self.assertEqual(cx.account.password, raw_password)

    def test_invalid_notification_url_error_and_logs_do_not_leak_token(self):
        secret_url = "sctapi.ftqq.com/SCT_SECRET_TOKEN_99999.send"
        with self.assertRaises(InputFormatError) as ctx:
            NotificationConfig(provider="ServerChan", url=secret_url)
        self.assertIn("notification.url", str(ctx.exception))
        self.assertNotIn("SCT_SECRET_TOKEN_99999", str(ctx.exception))

        logged = []
        with patch("main.init_config", return_value=({}, {}, {"provider": "ServerChan", "url": secret_url}, None)), \
             patch("main.logger.error", side_effect=lambda msg, *a, **kw: logged.append(str(msg))):
            with self.assertRaises(InputFormatError) as main_ctx:
                main.main()

        self.assertNotIn("SCT_SECRET_TOKEN_99999", str(main_ctx.exception))
        self.assertNotIn("SCT_SECRET_TOKEN_99999", "\n".join(logged))


if __name__ == "__main__":
    unittest.main()
