# -*- coding: utf-8 -*-
from api.tiku.adapter import TikuAdapter
from api.tiku.ai import AI
from api.tiku.go import TikuGo
from api.tiku.like import TikuLike
from api.tiku.manual import TikuManual
from api.tiku.siliconflow import SiliconFlow
from api.tiku.yanxi import TikuYanxi


PROVIDER_REGISTRY = {
    'TikuYanxi': TikuYanxi,
    'TikuGo': TikuGo,
    'TikuLike': TikuLike,
    'TikuAdapter': TikuAdapter,
    'AI': AI,
    'SiliconFlow': SiliconFlow,
    'TikuManual': TikuManual,
}
