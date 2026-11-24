# -*- coding: utf-8 -*-
"""超星客户端核心子包：静态导出全部子模块符号以保证兼容与打包发现."""
from api.client import (  # noqa: F401
    chaoxing,
    course,
    login,
    models,
    session,
    sign,
    video,
    work,
    work_parser,
)
from api.client.chaoxing import Chaoxing
from api.client.models import (
    Account,
    ActivityStatus,
    ActivityType,
    RateLimiter,
    SignType,
    StudyResult,
    get_timestamp,
)
from api.client.session import SessionManager
from api.client.work_parser import (
    _JUDGE_FALSE_SET,
    _JUDGE_TRUE_SET,
    _parse_work_record_detail,
    _parse_work_record_list,
    best_option_by_similarity,
    clean_res,
    get_option_text,
    is_subsequence,
    multi_cut,
    normalize_answer_text,
    normalize_text,
    random_answer,
)

__all__ = [
    "Chaoxing",
    "SessionManager",
    "Account",
    "RateLimiter",
    "StudyResult",
    "SignType",
    "ActivityStatus",
    "ActivityType",
    "get_timestamp",
    "multi_cut",
    "clean_res",
    "normalize_text",
    "get_option_text",
    "best_option_by_similarity",
    "is_subsequence",
    "random_answer",
    "_parse_work_record_list",
    "_parse_work_record_detail",
    "normalize_answer_text",
    "_JUDGE_TRUE_SET",
    "_JUDGE_FALSE_SET",
]
