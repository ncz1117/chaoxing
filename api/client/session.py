# -*- coding: utf-8 -*-
"""线程隔离的 HTTP Session 与 Cookie 代次同步管理."""
import functools
import threading

import requests
from loguru import logger
from requests.adapters import HTTPAdapter
from typing_extensions import Self

from api.config import GlobalConst as gc
from api.cookies import use_cookies


class SessionManager:
    _instance = None
    _instance_lock = threading.Lock()
    _login_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._local = threading.local()
                cls._instance._cookie_generation = 0
                cls._instance._cookie_snapshot = None
        return cls._instance

    @property
    def _session(self) -> requests.Session:
        # 每个线程复用自己的连接池，避免跨线程共享可变 Session
        if not hasattr(self._local, "session"):
            self._local.session = self._create_session()
            self._local.cookie_generation = -1
        self._sync_cookies(self._local.session)
        return self._local.session

    def _sync_cookies(self, session: requests.Session) -> None:
        with self._instance_lock:
            generation = self._cookie_generation
            if getattr(self._local, "cookie_generation", -1) == generation:
                return
            cookies = self._cookie_snapshot.copy() if self._cookie_snapshot is not None else use_cookies()
        session.cookies.clear()
        session.cookies.update(cookies)
        self._local.cookie_generation = generation

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        session.mount("https://", HTTPAdapter(max_retries=10))
        session.mount("http://", HTTPAdapter(max_retries=10))
        original_request = session.request

        def synced_request(method, url, **kwargs):
            self._sync_cookies(session)
            return original_request(method, url, **kwargs)

        session.request = functools.partial(synced_request, timeout=5)
        # For debug purposes
        # session.verify=False
        session.headers.clear()
        session.headers.update(gc.HEADERS)
        return session

    @classmethod
    def get_instance(cls) -> Self:
        return cls()

    @classmethod
    def get_session(cls) -> requests.Session:
        instance = cls.get_instance()
        return instance._session

    @classmethod
    def update_cookies(cls):
        with cls._instance_lock:
            instance = cls._instance
            if instance is not None:
                instance._cookie_snapshot = None
                instance._cookie_generation += 1
        if instance is not None and hasattr(instance._local, "session"):
            # 当前线程可能仍持有该 Session 引用，立即同步同一个对象
            instance._sync_cookies(instance._local.session)

    @classmethod
    def publish_cookies(cls, source_session: requests.Session):
        """在内存中同步验证后的完整 CookieJar，保留域和路径属性。"""
        instance = cls.get_instance()
        with cls._instance_lock:
            instance._cookie_snapshot = source_session.cookies.copy()
            instance._cookie_generation += 1
            if getattr(instance._local, "session", None) is source_session:
                instance._local.cookie_generation = instance._cookie_generation

    @classmethod
    def close_session(cls):
        instance = cls.get_instance()
        if hasattr(instance._local, "session"):
            instance._local.session.close()
            del instance._local.session

    @classmethod
    def relogin_if_needed(cls, chaoxing_instance) -> bool:
        with cls._login_lock:
            # 检查 cookie 会话是否仍然无效
            if chaoxing_instance._validate_cookie_session():
                return True

            logger.info("Cookie session invalid, attempting thread-safe relogin...")
            if chaoxing_instance.account and chaoxing_instance.account.username and chaoxing_instance.account.password:
                login_result = chaoxing_instance.login(login_with_cookies=False)
                if login_result.get("status"):
                    cls.update_cookies()
                    logger.info("Thread-safe relogin succeeded")
                    return True
                else:
                    logger.warning(f"Thread-safe relogin failed: {login_result.get('msg')}")
            return False
