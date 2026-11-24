# -*- coding: utf-8 -*-
"""向后兼容的题库模块再导出层，实际实现已拆分为 api.tiku 子包."""
from api.tiku import (
    AI,
    PROVIDER_REGISTRY,
    CacheDAO,
    DummyTiku,
    SiliconFlow,
    Tiku,
    TikuAdapter,
    TikuFallback,
    TikuGo,
    TikuLike,
    TikuManual,
    TikuYanxi,
)

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
