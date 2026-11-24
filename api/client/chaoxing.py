# -*- coding: utf-8 -*-
"""Chaoxing 主客户端类，组合登录、课程、签到、视频与测验 Mixin."""
from api.cipher import AESCipher
from api.client.course import CourseMixin
from api.client.login import LoginMixin
from api.client.models import Account, RateLimiter
from api.client.sign import SignMixin
from api.client.video import VideoMixin
from api.client.work import WorkMixin
from api.tiku.base import Tiku


class Chaoxing(LoginMixin, CourseMixin, SignMixin, VideoMixin, WorkMixin):
    def __init__(self, account: Account = None, tiku: Tiku = None, **kwargs):
        self.account = account
        self.cipher = AESCipher()
        self.tiku = tiku
        self.kwargs = kwargs
        self.rollback_times = 0
        self.rate_limiter = RateLimiter(0.5)  # 其他接口速率限制比较松
        self.video_log_limiter = RateLimiter(2)  # 上报进度极其容易卡验证码，限制2s一次
