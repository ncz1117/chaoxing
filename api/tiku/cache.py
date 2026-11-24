# -*- coding: utf-8 -*-
import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from api.logger import logger


class CacheDAO:
    """
    @Author: SocialSisterYi
    @Reference: https://github.com/SocialSisterYi/xuexiaoyi-to-xuexitong-tampermonkey-proxy
    """
    DEFAULT_CACHE_FILE = "cache.json"
    _registry_lock = threading.Lock()
    _path_locks: dict[Path, threading.RLock] = {}
    _path_caches: dict[Path, dict] = {}
    _path_sigs: dict[Path, Optional[tuple[int, int, int]]] = {}

    @classmethod
    def _get_lock_for_path(cls, path: Path) -> threading.RLock:
        with cls._registry_lock:
            lock = cls._path_locks.get(path)
            if lock is None:
                lock = threading.RLock()
                cls._path_locks[path] = lock
            return lock

    def __init__(self, file: Optional[str] = None):
        self.cache_file = Path(file or self.DEFAULT_CACHE_FILE)
        self._cache_key = self.cache_file.resolve()
        self._lock = self._get_lock_for_path(self._cache_key)
        self._ensure_loaded()

    @staticmethod
    def _stat_sig(path: Path) -> Optional[tuple[int, int, int]]:
        try:
            st = path.stat()
            return (st.st_mtime_ns, st.st_size, st.st_ino)
        except OSError:
            return None

    def _file_sig(self) -> Optional[tuple[int, int, int]]:
        return self._stat_sig(self.cache_file)

    def _ensure_loaded(self) -> dict:
        with self._lock:
            sig = self._file_sig()
            cached = self._path_caches.get(self._cache_key)
            cached_sig = self._path_sigs.get(self._cache_key)
            if cached is not None and sig is not None and sig == cached_sig:
                return dict(cached)
            if sig is None:
                data = {}
                written_sig = self._write_cache(data)
                if written_sig is not None:
                    self._path_caches[self._cache_key] = dict(data)
                    self._path_sigs[self._cache_key] = written_sig
                return data

            data: dict = {}
            for _ in range(3):
                sig_before = self._file_sig()
                if sig_before is None:
                    data = {}
                    written_sig = self._write_cache(data)
                    if written_sig is not None:
                        self._path_caches[self._cache_key] = dict(data)
                        self._path_sigs[self._cache_key] = written_sig
                    return data
                data = self._read_cache()
                sig_after = self._file_sig()
                if sig_after is not None and sig_before == sig_after:
                    snapshot = dict(data)
                    self._path_caches[self._cache_key] = snapshot
                    self._path_sigs[self._cache_key] = sig_after
                    return dict(snapshot)

            # 文件在读取期间持续被外部替换，不绑定内存签名，确保下次访问继续重读
            self._path_caches.pop(self._cache_key, None)
            self._path_sigs.pop(self._cache_key, None)
            return dict(data)

    def _recover_or_backup(self, error_label: str) -> dict:
        # 尝试从原始二进制中以 utf-8 忽略错误地恢复有效 JSON 段
        try:
            raw = self.cache_file.read_bytes()
            text = raw.decode("utf-8", errors="ignore")
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and start < end:
                try:
                    recovered = json.loads(text[start:end + 1])
                    if isinstance(recovered, dict):
                        return recovered
                except Exception:
                    pass
        except Exception:
            pass
        # 若无法恢复，备份损坏文件并返回空缓存
        try:
            bak_name = f"{self.cache_file.name}.bak.{int(time.time())}"
            bak_path = self.cache_file.with_name(bak_name)
            shutil.copy2(self.cache_file, bak_path)
            logger.error(f"{error_label}，已备份为: {bak_path}，将使用空缓存继续运行")
        except Exception as ex:
            logger.error(f"备份损坏缓存失败: {ex}")
        return {}

    def _read_cache(self) -> dict:
        # 新增缓存文件读取的异常处理
        try:
            with self._lock:
                if not self.cache_file.is_file():
                    return {}
                try:
                    with self.cache_file.open("r", encoding="utf8") as fp:
                        data = json.load(fp)
                    if not isinstance(data, dict):
                        logger.error("缓存文件根节点不是 JSON 对象，尝试恢复...")
                        return self._recover_or_backup("缓存文件格式异常")
                    return data
                except json.JSONDecodeError as e:
                    logger.error(f"缓存文件 JSON 解析失败: {e}, 尝试恢复...")
                    return self._recover_or_backup("缓存文件已损坏")
                except UnicodeDecodeError as e:
                    logger.error(f"缓存文件编码读取失败: {e}, 采用恢复策略...")
                    return self._recover_or_backup("缓存文件编码错误")
        except Exception as e:
            logger.error(f"读取缓存异常: {e}")
            return {}

    def _write_cache(self, data: dict) -> Optional[tuple[int, int, int]]:
        # 为缓存写入加锁，防止并发写入损坏文件
        try:
            with self._lock:
                parent = self.cache_file.parent
                if not parent.exists():
                    parent.mkdir(parents=True, exist_ok=True)
                # 写入临时文件后原子替换，减少并发写入时的损坏风险
                fd, tmp_path = tempfile.mkstemp(prefix=self.cache_file.name, dir=str(parent))
                try:
                    with os.fdopen(fd, "w", encoding="utf8") as fp:
                        json.dump(data, fp, ensure_ascii=False, indent=4)
                        fp.flush()
                        os.fsync(fp.fileno())
                    written_sig = self._stat_sig(Path(tmp_path))
                    os.replace(tmp_path, str(self.cache_file))
                    return written_sig
                except Exception as e:
                    # 清理临时文件
                    try:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    except Exception:
                        pass
                    logger.error(f"Failed to write cache atomically: {e}")
                    return None
        except IOError as e:
            logger.error(f"Failed to write cache: {e}")
            return None

    def get_cache(self, question: str) -> Optional[str]:
        with self._lock:
            data = self._ensure_loaded()
            return data.get(question)

    def add_cache(self, question: str, answer: str) -> None:
        # 为缓存写入加锁，防止并发写入损坏文件
        with self._lock:
            current = self._ensure_loaded()
            updated = dict(current)
            updated[question] = answer
            written_sig = self._write_cache(updated)
            if written_sig is not None:
                self._path_caches[self._cache_key] = updated
                self._path_sigs[self._cache_key] = written_sig
