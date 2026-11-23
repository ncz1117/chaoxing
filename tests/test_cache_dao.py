# -*- coding: utf-8 -*-
"""PR6 回归测试：死代码清理、CacheDAO 内存缓存与恢复、Tiku.query 单题路径修复."""
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402
from api.answer import CacheDAO, Tiku  # noqa: E402


class _MockSingleTiku(Tiku):
    def __init__(self, answers):
        super().__init__()
        self.name = "测试题库"
        self.true_list = ["正确"]
        self.false_list = ["错误"]
        self._answers = list(answers)
        self.calls = 0

    def _query(self, q_info: dict):
        self.calls += 1
        return self._answers.pop(0) if self._answers else None


class DeadCodeAndCacheTestCase(unittest.TestCase):
    def test_dead_code_removed_from_main(self):
        self.assertFalse(hasattr(main, "process_course"))
        processor = main.JobProcessor(
            None,
            [],
            {"speed": 1.0, "jobs": 1, "notopen_action": "retry"},
        )
        self.assertFalse(hasattr(processor, "wait_queue"))

    def test_cache_dao_reuses_memory_cache_without_rereading_disk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            cache_path.write_text(json.dumps({"已存在问题": "已有答案"}, ensure_ascii=False), encoding="utf-8")

            with patch.object(CacheDAO, "_read_cache", wraps=CacheDAO._read_cache, autospec=True) as mock_read:
                dao1 = CacheDAO(str(cache_path))
                self.assertEqual(mock_read.call_count, 1)

                self.assertEqual(dao1.get_cache("已存在问题"), "已有答案")
                dao1.add_cache("新问题", "新答案")
                self.assertEqual(dao1.get_cache("新问题"), "新答案")

                dao2 = CacheDAO(str(cache_path))
                self.assertEqual(dao2.get_cache("新问题"), "新答案")
                self.assertEqual(dao2.get_cache("已存在问题"), "已有答案")
                # 多次查询及跨实例实例化均命中内存缓存，未重复读盘
                self.assertEqual(mock_read.call_count, 1)

            persisted = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted, {"已存在问题": "已有答案", "新问题": "新答案"})

    def test_cache_dao_recovers_fragment_and_backs_up_unrecoverable_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recoverable = Path(tmpdir) / "recoverable.json"
            recoverable.write_text('garbage-prefix {"q1": "ans1"} garbage-suffix', encoding="utf-8")
            dao_ok = CacheDAO(str(recoverable))
            self.assertEqual(dao_ok.get_cache("q1"), "ans1")

            broken = Path(tmpdir) / "broken.json"
            broken.write_bytes(b"\xff\xfe not valid json at all")
            dao_bad = CacheDAO(str(broken))
            self.assertIsNone(dao_bad.get_cache("anything"))
            backups = list(Path(tmpdir).glob("broken.json.bak.*"))
            self.assertEqual(len(backups), 1)

            non_dict = Path(tmpdir) / "list.json"
            non_dict.write_text("[1, 2, 3]", encoding="utf-8")
            dao_list = CacheDAO(str(non_dict))
            self.assertIsNone(dao_list.get_cache("anything"))
            self.assertEqual(len(list(Path(tmpdir).glob("list.json.bak.*"))), 1)

    def test_cache_dao_concurrent_add_and_get(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "concurrent_cache.json"
            errors = []

            def worker(tid: int):
                try:
                    dao = CacheDAO(str(cache_path))
                    for i in range(10):
                        key = f"q-{tid}-{i}"
                        val = f"a-{tid}-{i}"
                        dao.add_cache(key, val)
                        self.assertEqual(dao.get_cache(key), val)
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(idx,)) for idx in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)
                self.assertFalse(t.is_alive())

            self.assertEqual(errors, [])
            persisted = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(len(persisted), 60)

    def test_tiku_query_returns_validated_answer_and_handles_redo_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(CacheDAO, "DEFAULT_CACHE_FILE", str(Path(tmpdir) / "tiku_cache.json")):
            tiku = _MockSingleTiku(["选项A", "选项B"])

            # 首次查询未命中缓存，应校验写缓存并返回结果
            ans1 = tiku.query({"title": "1单选题目", "type": "single"})
            self.assertEqual(ans1, "选项A")
            self.assertEqual(tiku.calls, 1)

            # 第二次同题命中缓存，不再调用 _query
            ans2 = tiku.query({"title": "1单选题目", "type": "single"})
            self.assertEqual(ans2, "选项A")
            self.assertEqual(tiku.calls, 1)

            # 重做模式设置 work_feedback：跳过缓存读、正常写缓存并返回新答案
            tiku.work_feedback = ["上次错了"]
            ans3 = tiku.query({"title": "1单选题目", "type": "single"})
            self.assertEqual(ans3, "选项B")
            self.assertEqual(tiku.calls, 2)
            self.assertEqual(CacheDAO().get_cache("单选题目"), "选项B")


if __name__ == "__main__":
    unittest.main()
