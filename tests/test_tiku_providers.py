# -*- coding: utf-8 -*-
"""PR10 回归测试：各题库 Provider 与 TikuFallback 回退链离线 Mock 测试."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api.tiku.adapter import TikuAdapter  # noqa: E402
from api.tiku.ai import AI  # noqa: E402
from api.tiku.base import Tiku  # noqa: E402
from api.tiku.fallback import TikuFallback  # noqa: E402
from api.tiku.go import TikuGo  # noqa: E402
from api.tiku.like import TikuLike  # noqa: E402
from api.tiku.manual import TikuManual  # noqa: E402
from api.tiku.siliconflow import SiliconFlow  # noqa: E402
from api.tiku.yanxi import TikuYanxi  # noqa: E402


def _json_response(status_code=200, payload=None, text=None):
    resp = requests.Response()
    resp.status_code = status_code
    if text is not None:
        resp._content = text.encode("utf-8")
    else:
        resp._content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    resp.encoding = "utf-8"
    return resp


class _MemoryCacheDAO:
    def __init__(self):
        self._store = {}

    def get_cache(self, title: str):
        return self._store.get(title)

    def add_cache(self, title: str, answer: str):
        self._store[title] = answer


class _StubProvider(Tiku):
    def __init__(self, name="Stub", handler=None, batch_handler=None):
        super().__init__()
        self.name = name
        self._handler = handler
        self._batch_handler = batch_handler
        self.true_list = ["正确", "对"]
        self.false_list = ["错误", "错"]
        self.feedback_received = []
        self.batch_calls = []

    def _query(self, q_info: dict):
        if self._handler:
            return self._handler(q_info)
        return None

    def query_all(self, q_list: list[dict], query_delay: float = 0.0):
        self.batch_calls.append(([q["title"] for q in q_list], query_delay))
        if self._batch_handler:
            return self._batch_handler(q_list, query_delay)
        return [None] * len(q_list)

    def set_work_feedback(self, feedback):
        self.feedback_received.append(feedback)


class TikuProvidersTestCase(unittest.TestCase):
    def _base_conf(self, **extra):
        conf = {
            "submit": "false",
            "cover_rate": "0.8",
            "true_list": "正确,对",
            "false_list": "错误,错",
            "ssl_verify": "true",
        }
        conf.update(extra)
        return conf

    def test_tiku_yanxi_success_token_rotation_exhaustion_and_http_error(self):
        provider = TikuYanxi()
        provider.config_set(self._base_conf(tokens="tok1,tok2", ssl_verify="false"))
        provider.init_tiku()
        self.assertEqual(provider._token, "tok1")
        self.assertIs(provider.ssl_verify, False)

        # 查询成功并更新剩余次数
        with patch("api.tiku.yanxi.requests.get", return_value=_json_response(200, {"code": 1, "data": {"answer": " 选项A ", "times": 42}})) as mock_get:
            ans = provider._query({"title": "测试题"})
        self.assertEqual(ans, "选项A")
        self.assertEqual(provider._times, 42)
        self.assertIs(mock_get.call_args.kwargs["verify"], False)

        # tok1 次数不足自动切换到 tok2 重试成功
        responses = [
            _json_response(200, {"code": 0, "message": "empty", "data": {"answer": "次数不足", "times": 0}}),
            _json_response(200, {"code": 1, "data": {"answer": "选项B", "times": 99}}),
        ]
        with patch("api.tiku.yanxi.requests.get", side_effect=responses):
            ans2 = provider._query({"title": "切换测试"})
        self.assertEqual(ans2, "选项B")
        self.assertEqual(provider._token, "tok2")

        # 全部 token 耗尽抛出 PermissionError
        with patch("api.tiku.yanxi.requests.get", return_value=_json_response(200, {"code": 0, "message": "quota", "data": {"answer": "次数不足"}})):
            with self.assertRaises(PermissionError):
                provider._query({"title": "耗尽测试"})

        # 非 200 返回 None
        with patch("api.tiku.yanxi.requests.get", return_value=_json_response(500, text="server error")):
            self.assertIsNone(provider._query({"title": "错误码测试"}))

    def test_tiku_adapter_maps_types_strips_options_and_handles_empty(self):
        provider = TikuAdapter()
        provider.config_set(self._base_conf(url="https://adapter.example/query"))
        provider.init_tiku()

        for q_type, expected_code in (
            ("single", 0),
            ("multiple", 1),
            ("completion", 2),
            ("judgement", 3),
            ("shortanswer", 4),
        ):
            with self.subTest(q_type=q_type), patch(
                "api.tiku.adapter.requests.post",
                return_value=_json_response(200, {"plat": 0, "answer": {"bestAnswer": ["甲", "乙"]}}),
            ) as mock_post:
                res = provider._query({"title": "题干", "options": "A. 甲\nB、乙\nC 丙", "type": q_type})
            self.assertEqual(res, "甲\n乙")
            sent_json = mock_post.call_args.kwargs["json"]
            self.assertEqual(sent_json["type"], expected_code)
            self.assertEqual(sent_json["options"], ["甲", "乙", "丙"])
            self.assertIs(mock_post.call_args.kwargs["verify"], True)

        with patch("api.tiku.adapter.requests.post", return_value=_json_response(200, {"plat": 0, "answer": {"bestAnswer": []}})):
            self.assertIsNone(provider._query({"title": "空答案", "options": "A. 1", "type": "single"}))

        with patch("api.tiku.adapter.requests.post", return_value=_json_response(502, text="bad gateway")):
            self.assertIsNone(provider._query({"title": "失败码", "options": "A. 1", "type": "single"}))

    def test_tiku_go_title_normalization_throttle_retry_and_placeholder(self):
        provider = TikuGo()
        provider.config_set(
            self._base_conf(
                go_authorization="auth-tok",
                go_min_interval="0",
                go_retry_times="3",
                go_retry_backoff="0.5",
            )
        )
        provider.init_tiku()

        # 带前缀未命中后，剥离【单选题】重试第二个候选标题命中
        with patch(
            "api.tiku.go.requests.post",
            side_effect=[
                _json_response(200, {"code": 0, "data": "", "msg": "未收录"}),
                _json_response(200, {"code": 1, "data": "正确答案", "msg": "ok"}),
            ],
        ):
            self.assertEqual(provider._query({"title": "【单选题】测试题目"}), "正确答案")

        # 流控提示触发退避重试后命中
        with patch(
            "api.tiku.go.requests.post",
            side_effect=[
                _json_response(200, {"code": 0, "data": "", "msg": "速度太快了"}),
                _json_response(200, {"code": 1, "data": "重试试成功", "msg": ""}),
                _json_response(200, {"code": 1, "data": "重试试成功", "msg": ""}),
            ],
        ), patch("api.tiku.go.time.sleep") as mock_sleep:
            self.assertEqual(provider._query({"title": "流控题"}), "重试试成功")
        mock_sleep.assert_called_once()

        # “李恒雅”占位文案且非流控时返回 None
        with patch(
            "api.tiku.go.requests.post",
            return_value=_json_response(200, {"code": 1, "data": "李恒雅正在努力撰写中...", "msg": ""}),
        ):
            self.assertIsNone(provider._query({"title": "占位题"}))

        # 非 JSON / HTTP 500 返回 None
        with patch("api.tiku.go.requests.post", return_value=_json_response(200, text="not-json")):
            self.assertIsNone(provider._query({"title": "坏JSON"}))
        with patch("api.tiku.go.requests.post", return_value=_json_response(500, text="err")):
            self.assertIsNone(provider._query({"title": "HTTP500"}))

    def test_tiku_like_parses_all_question_types_and_rotates_balance(self):
        provider = TikuLike()
        provider.config_set(
            self._base_conf(
                tokens="tok1,tok2",
                ssl_verify="false",
                likeapi_search="false",
                likeapi_vision="true",
                likeapi_retry="true",
                likeapi_retry_times="1",
            )
        )
        with patch("api.tiku.like.requests.get", side_effect=[_json_response(200, {"balance": 0}), _json_response(200, {"balance": 2})]):
            provider.init_tiku()
        self.assertEqual(provider._balance, {"tok1": 0, "tok2": 2})
        self.assertIs(provider._search, False)
        self.assertIs(provider._vision, True)

        # CHOICE / FILL_IN_BLANK / JUDGMENT 三种题型解析 + tok1 无余额时自动切换 tok2
        choice_resp = _json_response(
            200,
            {"results": {"output": {"questionType": "CHOICE", "answer": {"selectedOptions": ["A. 选项一", "B. 选项二"]}}}},
        )
        blank_resp = _json_response(
            200,
            {"results": {"output": {"questionType": "FILL_IN_BLANK", "answer": {"blanks": ["空1", "空2"]}}}},
        )
        judge_resp = _json_response(
            200,
            {"results": {"output": {"questionType": "JUDGMENT", "answer": {"isCorrect": True}}}},
        )
        with patch("api.tiku.like.random.choice", side_effect=["tok1", "tok2", "tok2"]), \
             patch("api.tiku.like.requests.post", side_effect=[choice_resp, blank_resp]) as mock_post:
            self.assertEqual(provider._query({"title": "多选", "type": "multiple", "options": ["A. 选项一", "B. 选项二"]}), "A. 选项一\nB. 选项二")
            self.assertEqual(provider._balance["tok2"], 1)
            self.assertEqual(provider._query({"title": "填空", "type": "completion", "options": ""}), "空1\n空2")
            self.assertEqual(provider._balance["tok2"], 0)

        self.assertEqual(mock_post.call_count, 2)
        self.assertIs(mock_post.call_args.kwargs["verify"], False)

        # 所有 token 余额耗尽 -> 直接返回 None，不再发起 post
        with patch("api.tiku.like.random.choice", return_value="tok2"), \
             patch("api.tiku.like.requests.post") as exhausted_post:
            self.assertIsNone(provider._query({"title": "无余额", "type": "judgement", "options": ""}))
        exhausted_post.assert_not_called()

        # 恢复余额后验证 JUDGMENT、401 和网络异常分支
        provider._balance["tok2"] = 2
        with patch("api.tiku.like.random.choice", return_value="tok2"), \
             patch("api.tiku.like.requests.post", return_value=judge_resp):
            self.assertEqual(provider._query({"title": "判断", "type": "judgement", "options": ""}), "正确")
        with patch("api.tiku.like.random.choice", return_value="tok2"), \
             patch("api.tiku.like.requests.post", return_value=_json_response(401, text="unauthorized")):
            self.assertIsNone(provider._query({"title": "未授权", "type": "single", "options": ["A"]}))
        with patch("api.tiku.like.random.choice", return_value="tok2"), \
             patch("api.tiku.like.requests.post", side_effect=requests.exceptions.ConnectionError("net down")):
            self.assertIsNone(provider._query({"title": "连接失败", "type": "single", "options": ["A"]}))

    def test_ai_parses_json_and_markdown_injects_feedback_and_deepseek_v4_flag(self):
        provider = AI()
        provider.config_set(
            self._base_conf(
                endpoint="https://api.deepseek.com/v1",
                key="sk-test",
                model="deepseek-v4-chat",
                http_proxy="",
                min_interval_seconds="0",
            )
        )
        provider.init_tiku()
        provider.set_work_feedback(["- 题目：第一题\n  正确答案：正确选项"])

        def _fake_completion(content):
            msg = Mock(content=content)
            choice = Mock(message=msg)
            return Mock(choices=[choice])

        mock_client = Mock()
        mock_client.chat.completions.create.side_effect = [
            _fake_completion('```json\n{"Answer": ["正确选项"]}\n```'),
            _fake_completion('{"Answer": ["选项A", "选项B"]}'),
            _fake_completion("invalid json"),
        ]

        with patch("api.tiku.ai.OpenAI", return_value=mock_client):
            ans1 = provider._query({"title": "单选题", "type": "single", "options": "A 正确选项\nB 错误选项"})
            ans2 = provider._query({"title": "多选题", "type": "multiple", "options": "A 选项A\nB 选项B"})
            ans3 = provider._query({"title": "异常题", "type": "completion", "options": ""})

        self.assertEqual(ans1, "正确选项")
        self.assertEqual(ans2, "选项A\n选项B")
        self.assertIsNone(ans3)

        first_call_kwargs = mock_client.chat.completions.create.call_args_list[0].kwargs
        self.assertEqual(first_call_kwargs["extra_body"], {"thinking": {"type": "disabled"}})
        roles = [m["role"] for m in first_call_kwargs["messages"]]
        self.assertEqual(roles, ["system", "system", "user"])
        self.assertIn("第一题", first_call_kwargs["messages"][1]["content"])

    def test_siliconflow_parses_markdown_json_and_handles_errors(self):
        provider = SiliconFlow()
        provider.config_set(
            self._base_conf(
                siliconflow_key="sf-tok",
                siliconflow_model="deepseek-ai/DeepSeek-V3",
                siliconflow_endpoint="https://api.siliconflow.cn/v1/chat/completions",
                min_interval_seconds="0",
            )
        )
        provider.init_tiku()

        ok_resp = _json_response(
            200,
            {"choices": [{"message": {"content": '```json\n{"Answer": ["答案文本"]}\n```'}}]},
        )
        with patch("api.tiku.siliconflow.requests.post", return_value=ok_resp) as mock_post:
            ans = provider._query({"title": "填空题", "type": "completion", "options": ""})
        self.assertEqual(ans, "答案文本")
        self.assertEqual(mock_post.call_args.kwargs["headers"]["Authorization"], "Bearer sf-tok")

        with patch("api.tiku.siliconflow.requests.post", return_value=_json_response(500, text="server err")):
            self.assertIsNone(provider._query({"title": "失败", "type": "single", "options": "A"}))

        with patch("api.tiku.siliconflow.requests.post", side_effect=requests.exceptions.Timeout("timeout")):
            self.assertIsNone(provider._query({"title": "超时", "type": "single", "options": "A"}))

    def test_tiku_manual_extract_letters_and_separator_init(self):
        self.assertEqual(TikuManual._extract_option_letters("a, c；D、"), ["A", "C", "D"])
        self.assertEqual(TikuManual._extract_option_letters("A1"), [])
        self.assertEqual(TikuManual._extract_option_letters(""), [])

        for raw_sep, expected_sep in (("space", " "), ("tab", "\t"), ("\\n", "\n")):
            with self.subTest(raw_sep=raw_sep):
                manual = TikuManual()
                manual.config_set(self._base_conf(manual_mode_default="single", manual_mode_separator=raw_sep))
                manual.init_tiku()
                self.assertEqual(manual.default_mode, "single")
                self.assertEqual(manual.separator, expected_sep)

    def test_tiku_fallback_chain_query_query_all_and_feedback_forwarding(self):
        p1 = _StubProvider(
            name="P1",
            handler=lambda q: "无效格式答案" if q["title"] == "类型不符" else (_ for _ in ()).throw(RuntimeError("boom")),
            batch_handler=lambda q_list, delay: ["选项A" if q["title"] == "题A" else None for q in q_list],
        )
        p2 = _StubProvider(
            name="P2",
            handler=lambda q: "正确",
            batch_handler=lambda q_list, delay: ["正确" for _ in q_list],
        )
        fb = TikuFallback([p1, p2])
        fb.config_set(self._base_conf())
        fb.init_tiku()

        mem_cache = _MemoryCacheDAO()
        with patch("api.tiku.base.CacheDAO", return_value=mem_cache):
            # p1 对判断题返回与题型不符的字符串时，回退 p2；p1 抛异常时同样回退 p2
            self.assertEqual(fb._query({"title": "类型不符", "type": "judgement", "options": ""}), "正确")
            self.assertEqual(fb._query({"title": "异常回退", "type": "judgement", "options": ""}), "正确")

            # query_all 会先剥离题号前缀（1题A -> 题A），并仅把 p1 未命中题目转发给 p2
            q_list = [
                {"title": "1题A", "type": "single", "options": "A. 选项A"},
                {"title": "2题判断", "type": "judgement", "options": ""},
            ]
            batch_ans = fb.query_all(q_list, query_delay=0.1)

        self.assertEqual(batch_ans, ["选项A", "正确"])
        self.assertEqual(p2.batch_calls, [(["题判断"], 0.1)])

        fb.set_work_feedback(["err1"])
        self.assertEqual(p1.feedback_received, [["err1"]])
        self.assertEqual(p2.feedback_received, [["err1"]])


if __name__ == "__main__":
    unittest.main()
