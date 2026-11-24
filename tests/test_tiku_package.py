# -*- coding: utf-8 -*-
"""PR7 回归测试：api.tiku 包拆分、兼容再导出、无循环导入及日志锁缓冲."""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import api.answer as answer_compat  # noqa: E402
import api.tiku as tiku_pkg  # noqa: E402
import api.tiku.registry as tiku_registry  # noqa: E402
from api.tiku.base import DummyTiku, Tiku  # noqa: E402
from api.tiku.fallback import TikuFallback  # noqa: E402
from api.tiku.yanxi import TikuYanxi  # noqa: E402


class TikuPackageTestCase(unittest.TestCase):
    def test_answer_compat_reexports_identical_objects(self):
        compat_lines = (ROOT / "api" / "answer.py").read_text(encoding="utf-8").splitlines()
        self.assertLess(len(compat_lines), 50)

        expected_symbols = [
            "CacheDAO",
            "Tiku",
            "DummyTiku",
            "TikuFallback",
            "TikuYanxi",
            "TikuGo",
            "TikuLike",
            "TikuAdapter",
            "AI",
            "SiliconFlow",
            "TikuManual",
            "PROVIDER_REGISTRY",
        ]
        self.assertEqual(set(answer_compat.__all__), set(expected_symbols))
        self.assertEqual(set(tiku_pkg.__all__), set(expected_symbols))
        for name in expected_symbols:
            self.assertIs(getattr(answer_compat, name), getattr(tiku_pkg, name))
        self.assertIs(answer_compat.PROVIDER_REGISTRY, tiku_registry.PROVIDER_REGISTRY)

    def test_direct_submodule_imports_have_no_circular_import(self):
        for mod_name in (
            "api.tiku.base",
            "api.tiku.cache",
            "api.tiku.manual",
            "api.tiku.registry",
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

    def test_get_tiku_from_config_variants(self):
        # 单 provider
        single = Tiku.get_tiku_from_config({"provider": "TikuYanxi", "tokens": "t1"})
        self.assertIsInstance(single, TikuYanxi)

        # 多 provider 回退链
        fb = Tiku.get_tiku_from_config({"provider": "TikuYanxi, TikuAdapter"})
        self.assertIsInstance(fb, TikuFallback)
        self.assertEqual([p.__class__.__name__ for p in fb.providers], ["TikuYanxi", "TikuAdapter"])

        # 无效 provider 回退 DummyTiku
        invalid = Tiku.get_tiku_from_config({"provider": "NonExistentTiku"})
        self.assertIsInstance(invalid, DummyTiku)
        self.assertTrue(invalid.DISABLE)

        # 空配置 / 缺失配置文件回退 DummyTiku
        empty = Tiku.get_tiku_from_config(config={}, config_path=str(ROOT / "missing_config.ini"))
        self.assertIsInstance(empty, DummyTiku)
        self.assertTrue(empty.DISABLE)

    def test_logger_tqdm_sink_buffers_when_only_tiku_manual_module_loaded(self):
        script = (
            "import io, sys\n"
            "import api.logger as al\n"
            "import api.tiku.manual as am\n"
            "assert 'api.answer' not in sys.modules\n"
            "buf = io.StringIO()\n"
            "al.tqdm_stream = buf\n"
            "al.log_buffer.clear()\n"
            "with am.TikuManual._manual_lock:\n"
            "    al.tqdm_sink('buffered-line\\n')\n"
            "    assert buf.getvalue() == ''\n"
            "    assert al.log_buffer == ['buffered-line\\n']\n"
            "al.tqdm_sink('flush-line\\n')\n"
            "assert al.log_buffer == []\n"
            "out = buf.getvalue()\n"
            "assert 'buffered-line' in out and 'flush-line' in out, out\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)


if __name__ == "__main__":
    unittest.main()
