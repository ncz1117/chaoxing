# -*- coding: utf-8 -*-
from abc import ABC, abstractmethod
from collections.abc import Mapping
import configparser
import os
import random
from re import sub
import time
from typing import Optional, Union

from api.answer_check import check_answer
from api.config import TikuConfig, parse_submit_flag, str_to_bool
from api.logger import logger
from api.tiku.cache import CacheDAO


class Tiku(ABC):
    CONFIG_PATH = os.path.join(os.getcwd(), "config.ini")
    DISABLE = False  # 停用标志
    SUBMIT = False  # 提交标志
    COVER_RATE = 0.8  # 覆盖率
    ssl_verify = True  # 默认校验题库 TLS 证书
    true_list = None
    false_list = None

    def __init__(self, config_path: Optional[str] = None) -> None:
        """
        初始化题库基类。

        Args:
            config_path: 配置文件路径，若为 None 则使用默认的 CONFIG_PATH。
        """
        self._name = None
        self._api = None
        self._conf = None
        self._config_path = config_path or self.CONFIG_PATH
        self.true_list = []
        self.false_list = []

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        self._name = value

    @property
    def api(self):
        return self._api

    @api.setter
    def api(self, value):
        self._api = value

    @property
    def token(self):
        return self._token

    @token.setter
    def token(self, value):
        self._token = value

    def init_tiku(self):
        # 仅用于题库初始化, 应该在题库载入后作初始化调用, 随后才可以使用题库
        # 尝试根据配置文件设置提交模式
        if not self._conf:
            self.config_set(self._get_conf())
        if self._conf is not None:
            self.ssl_verify = str_to_bool(self._conf.get("ssl_verify", True), default=True)
        if not self.DISABLE:
            # 设置提交模式
            self.SUBMIT = parse_submit_flag(self._conf.get("submit", False))
            self.COVER_RATE = float(self._conf.get("cover_rate", self.COVER_RATE))
            raw_true = self._conf.get("true_list", "正确,对,√,是")
            self.true_list = raw_true.split(",") if isinstance(raw_true, str) else [str(item) for item in raw_true]
            raw_false = self._conf.get("false_list", "错误,错,×,否,不对,不正确")
            self.false_list = raw_false.split(",") if isinstance(raw_false, str) else [str(item) for item in raw_false]
            # 调用自定义题库初始化
            self._init_tiku()

    def _init_tiku(self):
        # 仅用于题库初始化, 例如配置token, 交由自定义题库完成
        pass

    def config_set(self, config):
        if config is None or isinstance(config, TikuConfig):
            self._conf = config
        elif isinstance(config, Mapping):
            self._conf = TikuConfig.from_mapping(config)
        else:
            self._conf = config

    def _get_conf(self):
        """
        从默认配置文件查询配置, 如果未能查到, 停用题库
        """
        try:
            config = configparser.ConfigParser()
            config.read(self._config_path, encoding="utf8")
            return TikuConfig.from_mapping(config["tiku"])
        except (KeyError, FileNotFoundError):
            logger.info("未找到tiku配置, 已忽略题库功能")
            self.DISABLE = True
            return None

    @property
    def _is_manual_mode(self) -> bool:
        return (
                getattr(self, 'is_manual', False) or
                self.__class__.__name__ == 'TikuManual' or
                (self.__class__.__name__ == 'TikuFallback' and any(
                    getattr(p, 'is_manual', False) or p.__class__.__name__ == 'TikuManual' for p in
                    getattr(self, 'providers', [])))
        )

    def query(self, q_info: dict) -> Optional[str]:
        if self.DISABLE:
            return None

        # 预处理, 去除【单选题】这样与标题无关的字段
        if not self._is_manual_mode:
            logger.debug(f"原始标题：{q_info['title']}")
        q_info['title'] = sub(r'^\d+', '', q_info['title'])
        q_info['title'] = sub(r'（\d+\.\d+分）$', '', q_info['title'])
        if not self._is_manual_mode:
            logger.debug(f"处理后标题：{q_info['title']}")

        # 先过缓存（若存在章节检测错误反馈，说明处于重做模式，跳过缓存让大模型参考反馈重新作答）
        cache_dao = CacheDAO()
        if not getattr(self, 'work_feedback', None):
            answer = cache_dao.get_cache(q_info['title'])
            if answer:
                logger.info(f"从缓存中获取答案：{q_info['title']} -> {answer}")
                return answer.strip()

        answer = self._query(q_info)
        if answer:
            answer = answer.strip()
            logger.info(f"从{self.name}获取答案：{q_info['title']} -> {answer}")
            if check_answer(answer, q_info['type'], self):
                cache_dao.add_cache(q_info['title'], answer)
                return answer
            else:
                logger.info(f"从{self.name}获取到的答案类型与题目类型不符，已舍弃")
                return None

        logger.error(f"从{self.name}获取答案失败：{q_info['title']}")
        return None

    def query_all(self, q_list: list[dict], query_delay: float = 0.0) -> list[Optional[str]]:
        if self.DISABLE:
            return [None] * len(q_list)

        results = [None] * len(q_list)
        pending_indices = []

        cache_dao = CacheDAO()
        skip_cache = bool(getattr(self, 'work_feedback', None))
        for idx, q in enumerate(q_list):
            if not self._is_manual_mode:
                logger.debug(f"原始标题：{q['title']}")
            q['title'] = sub(r'^\d+', '', q['title'])
            q['title'] = sub(r'（\d+\.\d+分）$', '', q['title'])
            if not self._is_manual_mode:
                logger.debug(f"处理后标题：{q['title']}")

            if skip_cache:
                # 重做模式：不走缓存，让大模型参考错误反馈重新作答
                pending_indices.append(idx)
                continue

            answer = cache_dao.get_cache(q['title'])
            if answer:
                logger.info(f"从缓存中获取答案：{q['title']} -> {answer}")
                results[idx] = answer.strip()
            else:
                pending_indices.append(idx)

        if not pending_indices:
            return results

        sub_q_list = [q_list[idx] for idx in pending_indices]
        sub_results = self._query_all(sub_q_list, query_delay=query_delay)

        if not isinstance(sub_results, list):
            logger.error(f"{self.name} _query_all 返回结果格式异常，期望列表")
            sub_results = [None] * len(pending_indices)
        elif len(sub_results) != len(pending_indices):
            logger.error(
                f"{self.name} _query_all 返回结果长度不匹配，期望 {len(pending_indices)}，实际 {len(sub_results)}")
            # 补齐或截断 sub_results 防止错位
            sub_results = list(sub_results) + [None] * (len(pending_indices) - len(sub_results))
            sub_results = sub_results[:len(pending_indices)]

        for idx, ans in zip(pending_indices, sub_results):
            q_info = q_list[idx]
            if ans:
                ans = ans.strip()
                logger.info(f"从{self.name}获取答案：{q_info['title']} -> {ans}")
                if check_answer(ans, q_info['type'], self):
                    cache_dao.add_cache(q_info['title'], ans)
                    results[idx] = ans
                else:
                    logger.info(f"从{self.name}获取到的答案类型与题目类型不符，已舍弃")
            else:
                logger.error(f"从{self.name}获取答案失败：{q_info['title']}")

        return results

    @abstractmethod
    def _query(self, q_info: dict) -> Optional[str]:
        """
        查询接口, 交由自定义题库实现
        """
        pass


    def set_work_feedback(self, feedback) -> None:
        """
        设置上一轮章节检测的错误反馈，供支持反馈的大模型题库在重新作答时参考。

        Args:
            feedback: 错误反馈，可以是 str 或 list[str]（描述哪些题目答错、正确答案是什么）
        """
        pass

    def _query_all(self, q_list: list[dict], query_delay: float = 0.0) -> list[Optional[str]]:
        """
        批量查询的实现接口，默认循环调用单个查询 _query。
        子类若有批量查询或交互需求（如手动模式），可重写此方法。
        """
        results = []
        for q in q_list:
            if query_delay > 0:
                time.sleep(query_delay)
            try:
                results.append(self._query(q))
            except Exception as e:
                logger.error(f"{self.name} 查询单个题目发生异常: {e}")
                results.append(None)
        return results

    @staticmethod
    def get_tiku_from_config(
        config: Optional[Union[TikuConfig, Mapping]] = None,
        config_path: Optional[str] = None,
    ):
        """
        从配置文件加载题库, 这个配置可以是用户提供, 可以是默认配置文件
        """
        path = config_path or Tiku.CONFIG_PATH
        conf = TikuConfig.from_mapping(config) if config else None
        if not conf:
            # 尝试从默认配置文件加载
            try:
                config_parser = configparser.ConfigParser()
                config_parser.read(path, encoding="utf8")
                conf = TikuConfig.from_mapping(config_parser["tiku"])
            except (KeyError, FileNotFoundError):
                logger.error("未找到题库配置, 已忽略题库功能")
                dummy = DummyTiku(config_path=path)
                return dummy

        providers = conf.providers
        if not providers:
            if not conf.provider:
                logger.error("未找到题库配置, 已忽略题库功能")
            else:
                logger.error("题库provider配置为空, 已忽略题库功能")
            dummy = DummyTiku(config_path=path)
            return dummy

        from api.tiku.fallback import TikuFallback
        from api.tiku.registry import PROVIDER_REGISTRY

        invalid_providers = [name for name in providers if name not in PROVIDER_REGISTRY]
        if invalid_providers:
            logger.error(f"题库provider配置无效: {', '.join(invalid_providers)}")
            dummy = DummyTiku(config_path=path)
            return dummy

        if len(providers) == 1:
            provider_cls = PROVIDER_REGISTRY[providers[0]]
            if not isinstance(provider_cls, type) or not issubclass(provider_cls, Tiku):
                logger.error(f"题库provider配置无效: {providers[0]}")
                dummy = DummyTiku(config_path=path)
                return dummy
            new_cls = provider_cls(config_path=path)
            new_cls.config_set(conf)
            return new_cls

        chain_providers = []
        for provider_name in providers:
            provider_cls = PROVIDER_REGISTRY[provider_name]
            if not isinstance(provider_cls, type) or not issubclass(provider_cls, Tiku):
                logger.error(f"题库provider配置无效: {provider_name}")
                dummy = DummyTiku(config_path=path)
                return dummy
            provider = provider_cls(config_path=path)
            provider.config_set(conf)
            chain_providers.append(provider)
        fallback = TikuFallback(chain_providers, config_path=path)
        fallback.config_set(conf)
        return fallback

    def judgement_select(self, answer: str) -> bool:
        """
        这是一个专用的方法, 要求配置维护两个选项列表, 一份用于正确选项, 一份用于错误选项, 以应对题库对判断题答案响应的各种可能的情况
        它的作用是将获取到的答案answer与可能的选项列对比并返回对应的布尔值
        """
        if self.DISABLE:
            return False
        # 对响应的答案作处理
        answer = answer.strip().lower()

        # 内置的高频通用判断词规整
        if answer in ['true', 't', '1', '对', '正确', '√', '是', 'yes', 'y']:
            return True
        if answer in ['false', 'f', '0', '错', '错误', '×', '否', 'no', 'n', '不对', '不正确']:
            return False

        # 兼容自定义配置列表
        if answer in [x.lower() for x in self.true_list] or answer in self.true_list:
            return True
        elif answer in [x.lower() for x in self.false_list] or answer in self.false_list:
            return False
        else:
            # 无法判断, 随机选择
            logger.error(
                f'无法判断答案 -> {answer} 对应的是正确还是错误, 请自行判断并加入配置文件重启脚本, 本次将会随机选择选项')
            return random.choice([True, False])

    def get_submit_params(self):
        """
        这是一个专用方法, 用于根据当前设置的提交模式, 响应对应的答题提交API中的pyFlag值
        """
        # 留空直接提交, 1保存但不提交
        if self.SUBMIT:
            return ""
        else:
            return "1"

    def check_llm_connection(self) -> bool:
        """
        检查大模型连接是否可用
        默认返回 True（非大模型题库不需要检查）
        """
        return True


class DummyTiku(Tiku):
    def __init__(self, config_path: Optional[str] = None) -> None:
        """初始化空题库."""
        super().__init__(config_path)
        self.name = '空/禁用题库'
        self.DISABLE = True

    def _query(self, q_info: dict) -> Optional[str]:
        return None
