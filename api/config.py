# -*- coding: utf-8 -*-
"""全局常量及统一强类型配置模型与解析校验."""
from collections.abc import Mapping
import configparser
from dataclasses import dataclass, field, fields
import math
from pathlib import Path
from typing import Any, Optional, Union

from api.exceptions import InputFormatError

_TRUE_BOOL_VALUES = frozenset({"1", "true", "yes", "y", "on"})
_FALSE_BOOL_VALUES = frozenset({"0", "false", "no", "n", "off"})
_ALLOWED_NOTOPEN_ACTIONS = frozenset({"retry", "ask", "continue"})
_ALLOWED_MANUAL_MODES = frozenset({"batch", "single"})

_DEFAULT_SILICONFLOW_MODEL = "deepseek-ai/DeepSeek-V3"
_DEFAULT_SILICONFLOW_ENDPOINT = "https://api.siliconflow.cn/v1/chat/completions"
_DEFAULT_TRUE_LIST = "正确,对,√,是"
_DEFAULT_FALSE_LIST = "错误,错,×,否,不对,不正确"


class GlobalConst:
    AESKey = "u2oh6Vu^HWe4_AES"
    COOKIES_PATH = "cookies.txt"

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
        "sec-ch-ua": '"Chromium";v="118", "Google Chrome";v="118", "Not=A?Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }
    VIDEO_HEADERS = {
        "Referer": "https://mooc1.chaoxing.com/ananas/modules/video/index.html?v=2025-0725-1842",
    }
    AUDIO_HEADERS = {
        "Referer": "https://mooc1.chaoxing.com/ananas/modules/audio/index_new.html?v=2025-0725-1842",
    }

    THRESHOLD = 1


def str_to_bool(value: Any, default: bool = False) -> bool:
    """将布尔或常见布尔文本解析为 bool；空值与无法识别的值回退 default."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if not text:
        return default
    if text in _TRUE_BOOL_VALUES:
        return True
    if text in _FALSE_BOOL_VALUES:
        return False
    return default


def _clean_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _parse_int(value: Any, field_name: str, default: int, *, min_value: Optional[int] = None) -> int:
    if value is None:
        parsed = default
    elif isinstance(value, bool):
        raise InputFormatError(f"配置项 {field_name} 不能为布尔值: {value!r}")
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise InputFormatError(f"配置项 {field_name} 必须为整数，实际为: {value!r}")
        parsed = int(value)
    elif isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            parsed = default
        else:
            try:
                parsed = int(text)
            except ValueError as exc:
                raise InputFormatError(f"配置项 {field_name} 必须为整数，实际为: {value!r}") from exc
    else:
        raise InputFormatError(f"配置项 {field_name} 类型无效: {type(value).__name__}")

    if min_value is not None and parsed < min_value:
        raise InputFormatError(f"配置项 {field_name} 必须 >= {min_value}，实际为: {parsed}")
    return parsed


def _parse_float(
    value: Any,
    field_name: str,
    default: float,
    *,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
) -> float:
    if value is None:
        parsed = float(default)
    elif isinstance(value, bool):
        raise InputFormatError(f"配置项 {field_name} 不能为布尔值: {value!r}")
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            parsed = float(default)
        else:
            try:
                parsed = float(text)
            except ValueError as exc:
                raise InputFormatError(f"配置项 {field_name} 必须为数字，实际为: {value!r}") from exc
    else:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise InputFormatError(f"配置项 {field_name} 必须为数字，实际为: {value!r}") from exc

    if not math.isfinite(parsed):
        raise InputFormatError(f"配置项 {field_name} 必须为有限数字，实际为: {value!r}")
    if min_value is not None and parsed < min_value:
        raise InputFormatError(f"配置项 {field_name} 必须 >= {min_value}，实际为: {parsed}")
    if max_value is not None and parsed > max_value:
        raise InputFormatError(f"配置项 {field_name} 必须 <= {max_value}，实际为: {parsed}")
    return parsed


def _parse_course_list(value: Any) -> Optional[list[str]]:
    if value is None:
        return None
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",") if item.strip()]
        return items or None
    if isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value if str(item).strip()]
        return items or None
    raise InputFormatError(f"配置项 course_list 必须为字符串或列表，实际为: {type(value).__name__}")


def _parse_comma_list_str(value: Any, default: str) -> str:
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value if str(item).strip()]
        return ",".join(items) if items else default
    text = str(value).strip()
    return text or default


class _ConfigMappingMixin:
    """为配置 dataclass 提供向后兼容的只读字典接口与 from_mapping 工厂."""

    @classmethod
    def _public_field_names(cls) -> tuple[str, ...]:
        return tuple(
            f.name for f in fields(cls) if f.name != "extra" and not f.name.startswith("_")
        )

    @classmethod
    def from_mapping(cls, raw: Optional[Any]):
        if raw is None:
            return cls()
        if isinstance(raw, cls):
            return raw
        if not isinstance(raw, Mapping):
            raise InputFormatError(f"{cls.__name__} 需要映射类型配置，实际为: {type(raw).__name__}")

        public_names = set(cls._public_field_names())
        has_configured_flag = any(f.name == "_configured" for f in fields(cls))
        kwargs: dict[str, Any] = {}
        extra: dict[str, Any] = {}

        for key, val in raw.items():
            key_str = str(key)
            if key_str in public_names:
                kwargs[key_str] = val
            elif key_str == "extra" and isinstance(val, Mapping):
                extra.update({str(ek): ev for ek, ev in val.items()})
            elif not key_str.startswith("_"):
                extra[key_str] = val

        if extra:
            kwargs["extra"] = extra
        if has_configured_flag and len(raw) > 0:
            kwargs["_configured"] = True
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        merged = dict(self.extra) if hasattr(self, "extra") and self.extra else {}
        for name in self._public_field_names():
            merged[name] = getattr(self, name)
        return merged

    def __getitem__(self, key: str) -> Any:
        if key in self._public_field_names():
            return getattr(self, key)
        if hasattr(self, "extra") and key in self.extra:
            return self.extra[key]
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._public_field_names():
            return getattr(self, key)
        if hasattr(self, "extra") and key in self.extra:
            return self.extra[key]
        return default

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        return key in self._public_field_names() or (hasattr(self, "extra") and key in self.extra)

    def keys(self):
        return self.to_dict().keys()

    def items(self):
        return self.to_dict().items()


@dataclass
class CommonConfig(_ConfigMappingMixin):
    """[common] 节及命令行通用运行参数配置模型."""

    use_cookies: bool = False
    username: str = ""
    password: str = ""
    course_list: Optional[list[str]] = None
    speed: float = 1.0
    jobs: int = 4
    notopen_action: str = "retry"
    retry_interval: float = 1.0
    work_redo_enabled: bool = False
    work_max_retries: int = 3
    add_learning_count: bool = False
    target_count: int = 100
    auto_sign: bool = False
    verbose: bool = False
    extra: dict[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.use_cookies = str_to_bool(self.use_cookies, default=False)
        self.username = _clean_str(self.username)
        self.password = _clean_str(self.password)
        self.course_list = _parse_course_list(self.course_list)

        raw_speed = _parse_float(self.speed, "common.speed", 1.0)
        self.speed = min(2.0, max(1.0, raw_speed))

        self.jobs = _parse_int(self.jobs, "common.jobs", 4, min_value=1)

        action = _clean_str(self.notopen_action, "retry").lower() or "retry"
        if action not in _ALLOWED_NOTOPEN_ACTIONS:
            raise InputFormatError(
                f"配置项 common.notopen_action 仅允许 {sorted(_ALLOWED_NOTOPEN_ACTIONS)}，实际为: {self.notopen_action!r}"
            )
        self.notopen_action = action

        self.retry_interval = _parse_float(self.retry_interval, "common.retry_interval", 1.0, min_value=0.0)
        self.work_redo_enabled = str_to_bool(self.work_redo_enabled, default=False)
        self.work_max_retries = _parse_int(self.work_max_retries, "common.work_max_retries", 3, min_value=1)
        self.add_learning_count = str_to_bool(self.add_learning_count, default=False)
        self.target_count = _parse_int(self.target_count, "common.target_count", 100, min_value=1)
        self.auto_sign = str_to_bool(self.auto_sign, default=False)
        self.verbose = str_to_bool(self.verbose, default=False)
        self.extra = dict(self.extra) if self.extra else {}


@dataclass
class TikuConfig(_ConfigMappingMixin):
    """[tiku] 节题库配置模型."""

    provider: str = ""
    ssl_verify: bool = True
    check_llm_connection: bool = True
    submit: bool = False
    cover_rate: float = 0.8
    delay: float = 0.0
    tokens: str = ""
    url: str = ""
    likeapi_search: bool = False
    likeapi_vision: bool = True
    likeapi_model: str = ""
    likeapi_retry: bool = True
    likeapi_retry_times: int = 3
    go_authorization: str = ""
    go_min_interval: float = 1.0
    go_retry_times: int = 3
    go_retry_backoff: float = 1.2
    endpoint: str = ""
    key: str = ""
    model: str = ""
    min_interval_seconds: int = 3
    http_proxy: str = ""
    siliconflow_key: str = ""
    siliconflow_model: str = _DEFAULT_SILICONFLOW_MODEL
    siliconflow_endpoint: str = _DEFAULT_SILICONFLOW_ENDPOINT
    manual_mode_default: str = "batch"
    manual_mode_separator: str = ";"
    true_list: str = _DEFAULT_TRUE_LIST
    false_list: str = _DEFAULT_FALSE_LIST
    extra: dict[str, Any] = field(default_factory=dict, repr=False)
    _configured: bool = field(default=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.provider = _clean_str(self.provider)
        self.ssl_verify = str_to_bool(self.ssl_verify, default=True)
        self.check_llm_connection = str_to_bool(self.check_llm_connection, default=True)
        self.submit = str_to_bool(self.submit, default=False)
        self.cover_rate = _parse_float(self.cover_rate, "tiku.cover_rate", 0.8, min_value=0.0, max_value=1.0)
        self.delay = _parse_float(self.delay, "tiku.delay", 0.0, min_value=0.0)
        self.tokens = _clean_str(self.tokens)
        self.url = _clean_str(self.url)

        self.likeapi_search = str_to_bool(self.likeapi_search, default=False)
        self.likeapi_vision = str_to_bool(self.likeapi_vision, default=True)
        self.likeapi_model = _clean_str(self.likeapi_model)
        self.likeapi_retry = str_to_bool(self.likeapi_retry, default=True)
        self.likeapi_retry_times = _parse_int(self.likeapi_retry_times, "tiku.likeapi_retry_times", 3, min_value=1)

        self.go_authorization = _clean_str(self.go_authorization)
        self.go_min_interval = _parse_float(self.go_min_interval, "tiku.go_min_interval", 1.0, min_value=0.0)
        self.go_retry_times = _parse_int(self.go_retry_times, "tiku.go_retry_times", 3, min_value=1)
        self.go_retry_backoff = _parse_float(self.go_retry_backoff, "tiku.go_retry_backoff", 1.2, min_value=0.0)

        self.endpoint = _clean_str(self.endpoint)
        self.key = _clean_str(self.key)
        self.model = _clean_str(self.model)
        self.min_interval_seconds = _parse_int(self.min_interval_seconds, "tiku.min_interval_seconds", 3, min_value=0)
        self.http_proxy = _clean_str(self.http_proxy)

        self.siliconflow_key = _clean_str(self.siliconflow_key)
        self.siliconflow_model = _clean_str(self.siliconflow_model) or _DEFAULT_SILICONFLOW_MODEL
        self.siliconflow_endpoint = _clean_str(self.siliconflow_endpoint) or _DEFAULT_SILICONFLOW_ENDPOINT

        mode = _clean_str(self.manual_mode_default, "batch").lower() or "batch"
        if mode not in _ALLOWED_MANUAL_MODES:
            raise InputFormatError(
                f"配置项 tiku.manual_mode_default 仅允许 {sorted(_ALLOWED_MANUAL_MODES)}，实际为: {self.manual_mode_default!r}"
            )
        self.manual_mode_default = mode

        # 保留空格等空白分隔符，仅在 None 或空串时回退分号
        if self.manual_mode_separator is None or str(self.manual_mode_separator) == "":
            self.manual_mode_separator = ";"
        else:
            self.manual_mode_separator = str(self.manual_mode_separator)

        self.true_list = _parse_comma_list_str(self.true_list, _DEFAULT_TRUE_LIST)
        self.false_list = _parse_comma_list_str(self.false_list, _DEFAULT_FALSE_LIST)
        self.extra = dict(self.extra) if self.extra else {}

    @property
    def providers(self) -> list[str]:
        return [name.strip() for name in self.provider.split(",") if name.strip()]

    @property
    def true_values(self) -> list[str]:
        return [item for item in self.true_list.split(",") if item]

    @property
    def false_values(self) -> list[str]:
        return [item for item in self.false_list.split(",") if item]

    def __bool__(self) -> bool:
        return bool(
            self._configured
            or self.provider
            or self.tokens
            or self.url
            or self.key
            or self.siliconflow_key
            or self.submit
            or self.extra
        )


@dataclass
class NotificationConfig(_ConfigMappingMixin):
    """[notification] 节外部通知配置模型."""

    provider: str = ""
    url: str = ""
    tg_chat_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict, repr=False)
    _configured: bool = field(default=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.provider = _clean_str(self.provider)
        self.url = _clean_str(self.url)
        if self.url and not self.url.lower().startswith(("http://", "https://")):
            raise InputFormatError(
                f"配置项 notification.url 必须以 http:// 或 https:// 开头，实际为: {self.url!r}"
            )
        self.tg_chat_id = _clean_str(self.tg_chat_id)
        self.extra = dict(self.extra) if self.extra else {}

    def __bool__(self) -> bool:
        return bool(self._configured or self.provider or self.url or self.tg_chat_id or self.extra)


@dataclass
class AppConfig:
    """应用全量配置模型."""

    common: CommonConfig = field(default_factory=CommonConfig)
    tiku: TikuConfig = field(default_factory=TikuConfig)
    notification: NotificationConfig = field(default_factory=NotificationConfig)
    config_path: Optional[str] = None


def load_app_config(config_path: Union[str, Path]) -> AppConfig:
    """从 INI 配置文件读取并校验生成 AppConfig."""
    path_str = str(config_path)
    path_obj = Path(config_path)
    if not path_obj.is_file():
        raise FileNotFoundError(f"配置文件不存在: {path_str}")

    parser = configparser.ConfigParser()
    parser.read(path_str, encoding="utf8")

    common = (
        CommonConfig.from_mapping(dict(parser.items("common")))
        if parser.has_section("common")
        else CommonConfig()
    )
    tiku = (
        TikuConfig.from_mapping(dict(parser.items("tiku")))
        if parser.has_section("tiku")
        else TikuConfig()
    )
    notification = (
        NotificationConfig.from_mapping(dict(parser.items("notification")))
        if parser.has_section("notification")
        else NotificationConfig()
    )
    return AppConfig(
        common=common,
        tiku=tiku,
        notification=notification,
        config_path=path_str,
    )


def build_app_config_from_args(args) -> AppConfig:
    """从 argparse.Namespace 构建并校验 AppConfig."""
    common = CommonConfig(
        use_cookies=getattr(args, "use_cookies", False),
        username=getattr(args, "username", "") or "",
        password=getattr(args, "password", "") or "",
        course_list=getattr(args, "list", None),
        speed=1.0 if getattr(args, "speed", None) is None else args.speed,
        jobs=4 if getattr(args, "jobs", None) is None else args.jobs,
        notopen_action=getattr(args, "notopen_action", None) or "retry",
        retry_interval=1.0 if getattr(args, "retry_interval", None) is None else args.retry_interval,
        add_learning_count=getattr(args, "add_learning_count", False),
        target_count=100 if getattr(args, "target_count", None) is None else args.target_count,
        auto_sign=getattr(args, "auto_sign", False),
        verbose=getattr(args, "verbose", False),
    )
    return AppConfig(
        common=common,
        tiku=TikuConfig(),
        notification=NotificationConfig(),
        config_path=getattr(args, "config", None),
    )
