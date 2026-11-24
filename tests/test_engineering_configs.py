# -*- coding: utf-8 -*-
"""PR5 工程化回归测试：依赖清理、CI 工作流与 Docker 构建配置检查."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class EngineeringConfigTestCase(unittest.TestCase):
    def test_unused_app_shell_removed(self):
        self.assertFalse((ROOT / "app.py").exists())

    def test_requirements_cleaned_and_complete(self):
        lines = [
            line.strip()
            for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        pkg_names = {re.split(r"[<>=\[\]!~; ]", line, maxsplit=1)[0].lower() for line in lines}
        for removed in ("argparse", "celery", "flask"):
            self.assertNotIn(removed, pkg_names)
        self.assertIn("typing_extensions", pkg_names)

    def test_dockerfile_caches_deps_and_runs_as_non_root(self):
        content = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertNotRegex(content, r"(?m)^\s*COPY\s+\.")
        copy_req_idx = content.find("COPY requirements.txt")
        pip_install_idx = content.find("RUN pip install")
        copy_main_idx = content.find("COPY main.py config_template.ini /app/")
        self.assertNotEqual(copy_req_idx, -1)
        self.assertNotEqual(pip_install_idx, -1)
        self.assertNotEqual(copy_main_idx, -1)
        self.assertLess(copy_req_idx, pip_install_idx)
        self.assertLess(pip_install_idx, copy_main_idx)
        self.assertIn("COPY api /app/api", content)
        self.assertIn("COPY resource /app/resource", content)
        self.assertIn("ARG PYPI_MIRROR", content)
        self.assertIn("chown -R chaoxing:chaoxing /app /config", content)
        self.assertIn("USER chaoxing", content)

    def test_dockerignore_excludes_sensitive_and_build_files(self):
        dockerignore = ROOT / ".dockerignore"
        self.assertTrue(dockerignore.is_file())
        entries = [
            line.strip()
            for line in dockerignore.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        for item in (
            ".git",
            "*.log",
            ".*.log",
            ".cookies.txt",
            "*cookies*.txt",
            ".config.ini",
            "config*.ini",
            "!config_template.ini",
            "cache.json*",
            ".cache.json*",
            "myConfig",
            "start*.bat",
            ".env*",
        ):
            self.assertIn(item, entries)
        self.assertLess(entries.index("config*.ini"), entries.index("!config_template.ini"))

    def test_ci_workflow_runs_tests_and_gates_windows_release(self):
        workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")
        self.assertIn("pull_request:", workflow)
        self.assertIn("actions/checkout@v4", workflow)
        self.assertIn("actions/setup-python@v5", workflow)
        self.assertNotIn("actions/checkout@v3", workflow)
        self.assertNotIn("actions/setup-python@v3", workflow)
        self.assertRegex(workflow, r"(?m)^\s+test:\s*$")
        self.assertIn("ruff check .", workflow)
        self.assertIn("python -m unittest discover -s tests -v", workflow)
        self.assertIn("needs: test", workflow)
        self.assertIn(
            "if: github.event_name == 'workflow_dispatch' || startsWith(github.ref, 'refs/tags/')",
            workflow,
        )
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("[tool.ruff.lint]", pyproject)


if __name__ == "__main__":
    unittest.main()
