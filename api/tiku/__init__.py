# -*- coding: utf-8 -*-
from urllib3 import disable_warnings, exceptions

from api.tiku.adapter import TikuAdapter
from api.tiku.ai import AI
from api.tiku.base import DummyTiku, Tiku
from api.tiku.cache import CacheDAO
from api.tiku.fallback import TikuFallback
from api.tiku.go import TikuGo
from api.tiku.like import TikuLike
from api.tiku.manual import TikuManual
from api.tiku.registry import PROVIDER_REGISTRY
from api.tiku.siliconflow import SiliconFlow
from api.tiku.yanxi import TikuYanxi

# 关闭警告
disable_warnings(exceptions.InsecureRequestWarning)

__all__ = [
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
