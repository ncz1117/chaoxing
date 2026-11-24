# -*- coding: utf-8 -*-
"""超星账号登录、Cookie 会话校验与基础用户信息."""
import re

import requests
from loguru import logger
from requests import RequestException

from api.client.session import SessionManager
from api.config import GlobalConst as gc
from api.cookies import save_cookies


class LoginMixin:
    """登录、Cookie 校验与用户基础属性."""

    def login(self, login_with_cookies=False):
        if login_with_cookies:
            logger.info("Logging in with cookies")
            SessionManager.update_cookies()
            logger.debug("Logged in with cookies: {}", list(SessionManager.get_session().cookies.keys()))
            if not self._validate_cookie_session():
                logger.warning("Cookie 登录校验失败，尝试使用账号密码重新登录")
                if self.account and self.account.username and self.account.password:
                    return self.login(login_with_cookies=False)
                return {"status": False, "msg": "cookies 已失效，请更新 cookies 或提供账号密码"}
            logger.info("登录成功...")
            try:
                realname = self.get_name()
                if realname:
                    logger.info(f"当前登录用户: {realname}")
            except Exception as e:
                logger.debug(f"获取当前登录用户名失败: {e}")
            return {"status": True, "msg": "登录成功"}

        _session = requests.Session()
        _url = "https://passport2.chaoxing.com/fanyalogin"
        _data = {
            "fid": "-1",
            "uname": self.cipher.encrypt(self.account.username),
            "password": self.cipher.encrypt(self.account.password),
            "refer": "https%3A%2F%2Fi.chaoxing.com",
            "t": True,
            "forbidotherlogin": 0,
            "validate": "",
            "doubleFactorLogin": 0,
            "independentId": 0,
        }
        logger.trace("正在尝试登录...")
        try:
            resp = _session.post(_url, headers=gc.HEADERS, data=_data, timeout=10)
            resp.raise_for_status()
            payload = resp.json()
        except (RequestException, ValueError) as e:
            return {"status": False, "msg": f"登录请求失败: {e}"}

        if not isinstance(payload, dict):
            return {"status": False, "msg": "登录请求失败: 响应格式异常"}

        if payload.get("status") in (True, 1):
            save_cookies(_session)
            SessionManager.update_cookies()
            logger.info("登录成功...")
            try:
                realname = self.get_name()
                if realname:
                    logger.info(f"当前登录用户: {realname}")
            except Exception as e:
                logger.debug(f"获取当前登录用户名失败: {e}")
            return {"status": True, "msg": "登录成功"}
        return {"status": False, "msg": str(payload.get("msg2") or payload.get("msg") or "登录失败, 未知原因")}

    @staticmethod
    def get_name() -> str:
        _session = SessionManager.get_session()
        try:
            resp = _session.get("https://passport2.chaoxing.com/mooc/accountManage", timeout=10)
            if resp.status_code == 200:
                match = re.search(r'id="messageName"\s+value="([^"]*)"', resp.text)
                if match:
                    return match.group(1).strip()
        except Exception as e:
            logger.debug(f"获取用户名失败: {e}")
        return ""

    def _validate_cookie_session(self) -> bool:
        session = SessionManager.get_instance()._session
        if not session.cookies.get("_uid"):
            return False

        test_session = requests.Session()
        test_session.headers.update(gc.HEADERS)
        test_session.cookies.update(session.cookies.get_dict())

        try:
            resp = test_session.post(
                "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata",
                data={"courseType": 1, "courseFolderId": 0, "query": "", "superstarClass": 0},
                timeout=8,
            )
        except RequestException as exc:
            logger.debug("Cookie validation request failed: {}", exc)
            return False

        if resp.status_code != 200:
            return False

        if "passport2.chaoxing.com" in resp.text or "login" in resp.text.lower():
            return False

        return True

    def get_fid(self):
        _session = SessionManager.get_session()
        return _session.cookies.get("fid", 1024)

    def get_uid(self):
        s = SessionManager.get_session()
        if "_uid" in s.cookies:
            return s.cookies["_uid"]
        if "UID" in s.cookies:
            return s.cookies["UID"]
        raise ValueError("Cannot get uid !")
