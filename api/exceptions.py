try:
    from requests.exceptions import JSONDecodeError as JSONDecodeError
except ImportError:
    from json import JSONDecodeError as JSONDecodeError

__all__ = [
    "JSONDecodeError",
    "LoginError",
    "InputFormatError",
    "MaxRollBackExceeded",
    "MaxRetryExceeded",
    "FontDecodeError",
]


class LoginError(Exception):
    def __init__(self, *args: object):
        super().__init__(*args)


class InputFormatError(Exception):
    def __init__(self, *args: object):
        super().__init__(*args)


class MaxRollBackExceeded(Exception):
    def __init__(self, *args: object):
        super().__init__(*args)


class MaxRetryExceeded(Exception):
    def __init__(self, *args: object):
        super().__init__(*args)


class FontDecodeError(Exception):
    def __init__(self, *args: object):
        super().__init__(*args)
