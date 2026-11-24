# -*- coding: utf-8 -*-
"""章节测验答案匹配、文本归一化及作答记录页面解析."""
from difflib import SequenceMatcher
import random
import re

from loguru import logger

from api.answer_check import cut


def multi_cut(answer: str, origin_html_content="", logger=logger):
    """
    将多选题答案字符串按特定字符进行切割, 并返回切割后的答案列表
    """
    res = cut(answer)
    if res is None:
        logger.warning(
            f"未能从网页中提取题目信息, 以下为相关信息：\n\t{answer}\n\n{origin_html_content}\n"
        )
        logger.warning("未能正确提取题目选项信息! 请反馈并提供以上信息")
        return None
    else:
        return res


def clean_res(res):
    cleaned_res = []
    if isinstance(res, str):
        res = [res]
    for c in res:
        # 仅在字符串长度大于1时才尝试去除开头的字母编号，防止误删单个字母答案
        cleaned = re.sub(r'^[A-Za-z]\s*[.、:：)?）]?\s*|[.,!?;:，。！？；：]', '', c) if len(c) > 1 else c
        cleaned_res.append(cleaned.strip())
    return cleaned_res


def normalize_text(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)
    # 统一常见异体字符，降低“风/⻛”类差异导致的匹配失败。
    char_map = str.maketrans({
        '⻛': '风',
        '⻔': '门',
        '⻋': '车',
        '⻢': '马',
    })
    normalized = text.translate(char_map)
    normalized = re.sub(r'^[A-Za-z]\s*[.、:：)?）]?\s*', '', normalized)
    normalized = re.sub(r'\s+', '', normalized)
    normalized = re.sub(r'[，。！？；：,.!?;:()（）\[\]【】"“”‘’\-_/\\|]', '', normalized)
    return normalized.lower()


def get_option_text(option: str) -> str:
    return re.sub(r'^[A-Za-z]\s*[.、:：)?）]?\s*', '', option).strip()


def best_option_by_similarity(target: str, options: list, threshold: float = 0.8) -> str:
    if not target or not options:
        return ""
    target_norm = normalize_text(target)
    if not target_norm:
        return ""

    best_letter = ""
    best_score = 0.0
    for option in options:
        option_text = get_option_text(option)
        option_norm = normalize_text(option_text)
        if not option_norm:
            continue
        score = SequenceMatcher(None, target_norm, option_norm).ratio()
        if score > best_score:
            best_score = score
            best_letter = option[:1]

    if best_score >= threshold:
        logger.info(f"相似度兜底匹配成功: {best_letter} (score={best_score:.2f}, threshold={threshold:.2f})")
        return best_letter
    return ""


def is_subsequence(a, o):
    iter_o = iter(o.lower())
    return all(c in iter_o for c in a.lower())


def random_answer(options: str, q_type: str) -> str:
    answer = ""
    if not options:
        return answer

    if q_type == "multiple":
        logger.debug(f"当前选项列表[cut前] -> {options}")
        _op_list = multi_cut(options)
        logger.debug(f"当前选项列表[cut后] -> {_op_list}")

        if not _op_list:
            logger.error(
                "选项为空, 未能正确提取题目选项信息! 请反馈并提供以上信息"
            )
            return answer

        available_options = len(_op_list)
        select_count = 0

        # 根据可用选项数量调整可能选择的选项数
        if available_options <= 1:
            select_count = available_options
        else:
            max_possible = min(4, available_options)
            min_possible = min(2, available_options)

            weights_map = {
                2: [1.0],
                3: [0.3, 0.7],
                4: [0.1, 0.5, 0.4],
                5: [0.1, 0.4, 0.3, 0.2],
            }

            weights = weights_map.get(max_possible, [0.3, 0.4, 0.3])
            possible_counts = list(range(min_possible, max_possible + 1))

            weights = weights[:len(possible_counts)]

            weights_sum = sum(weights)
            if weights_sum > 0:
                weights = [w / weights_sum for w in weights]

            select_count = random.choices(possible_counts, weights=weights, k=1)[0]

        selected_options = random.sample(_op_list, select_count) if select_count > 0 else []

        for option in selected_options:
            answer += option[:1]  # 取首字为答案，例如A或B

        answer = "".join(sorted(answer))
    elif q_type == "single":
        answer = random.choice(options.split("\n"))[:1]  # 取首字为答案, 例如A或B
    # 判断题处理
    elif q_type == "judgement":
        answer = "true" if random.choice([True, False]) else "false"
    logger.info(f"随机选择 -> {answer}")
    return answer


def _parse_work_record_list(html_text: str) -> list[tuple[int, float]]:
    """
    解析章节检测作答记录列表页面（/work/record-list）。

    Args:
        html_text: record-list 页面 HTML

    Returns:
        作答记录列表，元素为 (作答序号times, 成绩score)，例如 [(0, 80.0), (1, 100.0)]
    """
    records = []
    times_list = re.findall(r'viewNum">第(\d+)次', html_text)
    scores = re.findall(r'viewScore">([\d.]+)分', html_text)
    if len(times_list) != len(scores):
        # 次数/成绩数量不齐时 zip 会错位, 成绩按 0 处理(放弃分数捷径, 仅做逐题比对)
        logger.warning(f"作答记录次数/成绩数量不匹配({len(times_list)}/{len(scores)}), 成绩按0处理")
        scores = ['0'] * len(times_list)
    for t, s in zip(times_list, scores):
        try:
            records.append((int(t), float(s)))
        except ValueError:
            continue
    return records


def _parse_work_record_detail(html_text: str) -> list[dict]:
    """
    解析章节检测单次作答详情页面（/work/record-detail）。

    Args:
        html_text: record-detail 页面 HTML

    Returns:
        每题信息列表：{id, title, type_label, my_answer, correct_answer}
    """
    questions = []
    for qm in re.finditer(r'<div class="TiMu[^"]*singleQuesId" data="(\d+)"[^>]*>(.*?)(?=<div class="TiMu|$)', html_text, re.S):
        qid = qm.group(1)
        qb = qm.group(2)

        # 题型 + 题目
        tm = re.search(r'newZy_TItle">(.*?)</span>(.*?)</div>', qb, re.S)
        if tm:
            type_label = re.sub(r'<[^>]+>', '', tm.group(1)).strip()
            title = re.sub(r'<[^>]+>', '', tm.group(2))
        else:
            type_label = ""
            title = ""
        title = re.sub(r'\s+', ' ', title).strip()

        # 我的答案/正确答案: 多模式匹配, 兼容属性顺序变化与额外 class 的页面变体
        ans_patterns = [
            r'{label}[:：]</span>\s*<div class="fl answerCon">\s*(.*?)\s*</div>',
            r'{label}[:：]\s*</span>\s*<div[^>]*class="[^"]*answerCon[^"]*"[^>]*>\s*(.*?)\s*</div>',
            r'{label}[:：]\s*</span>\s*<span[^>]*>\s*(.*?)\s*</span>',
        ]

        def _extract_answer(label):
            for pat in ans_patterns:
                m = re.search(pat.format(label=label), qb, re.S)
                if m:
                    return re.sub(r'<[^>]+>', '', m.group(1)).strip()
            return None

        my_raw = _extract_answer('我的答案')
        correct_raw = _extract_answer('正确答案')

        questions.append({
            "id": qid,
            "title": title,
            "type_label": type_label,
            "my_answer": my_raw or '',
            "correct_answer": correct_raw or '',
            "parse_ok": my_raw is not None and correct_raw is not None,
        })
    return questions


_JUDGE_TRUE_SET = {'TRUE', 'T', '1', '对', '正确', '√', '是', 'YES', 'Y'}
_JUDGE_FALSE_SET = {'FALSE', 'F', '0', '错', '错误', '×', 'X', '否', 'NO', 'N', '不对', '不正确'}


def normalize_answer_text(ans) -> str:
    """作答详情答案归一化: 消除 对/错与true/false、全半角标点等格式差异.

    归一化是确定性的, 两侧同格式必然相等; 跨格式差异(如字母 vs 选项全文)
    交由调用方的满分分数兜底处理.
    """
    s = re.sub(r'\s+', '', str(ans or '')).upper()
    if s in _JUDGE_TRUE_SET:
        return 'TRUE'
    if s in _JUDGE_FALSE_SET:
        return 'FALSE'
    if re.fullmatch(r'[A-Z0-9]+', s):
        return s
    s = re.sub(r'^[A-Z][.、:：)?）]', '', s)
    s = re.sub(r'[，。、！？；：,.!?;:()（）\[\]【】"“”‘’\-_/\\|]', '', s)
    return s


def _summarize_work_detail(detail: list[dict]) -> tuple[bool, list[str], int]:
    """汇总逐题作答比对结果（解析失配题跳过并计数，避免误判全错）."""
    feedback = []
    all_correct = True
    unknown = 0
    for q in detail:
        if not q.get("parse_ok", True):
            unknown += 1
            all_correct = False
            continue
        my_ans = (q.get("my_answer") or "").strip()
        correct_ans = (q.get("correct_answer") or "").strip()
        if normalize_answer_text(my_ans) != normalize_answer_text(correct_ans):
            all_correct = False
            feedback.append(
                f"- 题目：{q.get('title', '')}\n"
                f"  题型：{q.get('type_label', '')}\n"
                f"  你的上次答案：{my_ans or '(空)'}\n"
                f"  正确答案：{correct_ans or '(空)'}"
            )
    return all_correct, feedback, unknown
