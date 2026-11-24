# -*- coding: utf-8 -*-
"""章节测验/作业作答、提交与成绩核对流程."""
import re
import time
from typing import Optional

from loguru import logger
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_fixed

from api.client.models import StudyResult
from api.client.session import SessionManager
from api.client.work_parser import (
    _parse_work_record_detail,
    _parse_work_record_list,
    _summarize_work_detail,
    best_option_by_similarity,
    clean_res,
    is_subsequence,
    multi_cut,
    random_answer,
)
from api.decode import decode_questions_info

WORK_SUBMIT_HEADERS = {
    "Host": "mooc1.chaoxing.com",
    "sec-ch-ua-platform": '"Windows"',
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "sec-ch-ua": '"Microsoft Edge";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "sec-ch-ua-mobile": "?0",
    "Origin": "https://mooc1.chaoxing.com",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,ja;q=0.5",
}


def _is_not_permission_error(exception):
    return not isinstance(exception, PermissionError)


class WorkMixin:
    """章节测验：拉取题目、搜题填充、组卷提交与成绩校验."""

    def _resolve_work_redo_retries(self) -> int:
        # work_redo_enabled=false 时为单轮模式: 提交+检查+报告成绩, 不自动重做(适用于只允许作答一次的课程)
        if bool(self.kwargs.get("work_redo_enabled", False)):
            try:
                return max(1, int(self.kwargs.get("work_max_retries", 3)))
            except (TypeError, ValueError):
                return 3
        return 0

    def _is_manual_tiku(self) -> bool:
        return (
            getattr(self.tiku, "is_manual", False)
            or self.tiku.__class__.__name__ == "TikuManual"
            or (
                self.tiku.__class__.__name__ == "TikuFallback"
                and any(
                    getattr(p, "is_manual", False) or p.__class__.__name__ == "TikuManual"
                    for p in getattr(self.tiku, "providers", [])
                )
            )
        )

    def _fetch_work_questions(self, session, course: dict, job: dict, job_info: dict):
        """获取章节测验页面并解析题目信息（遇未创建测验立即跳过不重试）."""
        url = "https://mooc1.chaoxing.com/mooc-ans/api/work"

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_fixed(1),
            retry=retry_if_exception(_is_not_permission_error),
            reraise=True,
        )
        def _fetch_with_retry():
            resp = session.get(
                url,
                params={
                    "api": "1",
                    "workId": job["jobid"].replace("work-", ""),
                    "jobid": job["jobid"],
                    "originJobId": job["jobid"],
                    "needRedirect": "true",
                    "skipHeader": "true",
                    "knowledgeid": str(job_info["knowledgeid"]),
                    "ktoken": job_info["ktoken"],
                    "cpi": job_info["cpi"],
                    "ut": "s",
                    "clazzId": course["clazzId"],
                    "type": "",
                    "enc": job["enc"],
                    "mooc2": "1",
                    "courseid": course["courseId"],
                },
            )

            # 未创建完成该测验则不进行答题，目前遇到的情况是未创建完成等同于没题目
            if "教师未创建完成该测验" in resp.text:
                raise PermissionError("教师未创建完成该测验")

            questions = decode_questions_info(resp.text)

            if resp.status_code == 200 and questions.get("questions"):
                return resp, questions

            logger.warning(
                f"无效响应 (Code: {getattr(resp, 'status_code', 'Unknown')}), 重试中..."
            )
            raise RuntimeError(f"请求返回无效数据 (Code: {resp.status_code})")

        return _fetch_with_retry()

    def _match_question_answer(self, q: dict, res, origin_html: str) -> str:
        """将题库返回的答案按题型匹配到测验选项或作答文本."""
        answer = ""
        q_type = q["type"]
        if q_type == "multiple":
            options_list = multi_cut(q["options"], origin_html)
            res_list = multi_cut(res, origin_html)
            if res_list is not None and options_list is not None:
                for _a in clean_res(res_list):
                    matched = False
                    for o in options_list:
                        if is_subsequence(_a, o):
                            answer += o[:1]
                            matched = True
                            break  # 找到匹配项后立即停止，防止重复添加
                    if not matched:
                        best_letter = best_option_by_similarity(_a, options_list, threshold=0.8)
                        if best_letter:
                            answer += best_letter
                # 对答案进行排序, 否则会提交失败
                answer = "".join(sorted(set(answer)))
        elif q_type == "single":
            # 单选也进行切割，主要是防止返回的答案有异常字符
            options_list = multi_cut(q["options"], origin_html)
            if options_list is not None:
                t_res = clean_res(res)
                if t_res:
                    for o in options_list:
                        if is_subsequence(t_res[0], o):
                            answer = o[:1]
                            break
                    if not answer:
                        answer = best_option_by_similarity(t_res[0], options_list, threshold=0.8)
        elif q_type == "judgement":
            answer = "true" if self.tiku.judgement_select(res) else "false"
        elif q_type == "completion":
            if isinstance(res, list):
                answer = "".join(res)
            elif isinstance(res, str):
                answer = res
        else:
            # 其他类型直接使用答案 （目前仅知有简答题，待补充处理）
            answer = res
        return answer

    def _query_and_fill_work_answers(
        self,
        questions: dict,
        origin_html: str,
        query_delay=0,
        feedback_history=None,
    ) -> tuple[int, float]:
        """向题库查题并填充各题 answerField，返回 (总题数, 覆盖率百分比)."""
        if feedback_history and hasattr(self.tiku, "set_work_feedback"):
            try:
                self.tiku.set_work_feedback(feedback_history)
                logger.debug("已将上一轮错误反馈设置到题库")
            except Exception as e:
                logger.warning(f"设置题库错误反馈失败: {e}")

        question_items = questions["questions"]
        total_questions = len(question_items)
        found_answers = 0
        answers = self.tiku.query_all(question_items, query_delay=query_delay)

        if not isinstance(answers, list):
            logger.error("题库 query_all 返回的数据格式异常，期望列表。将采用随机答案答题")
            answers = [None] * total_questions
        elif len(answers) != total_questions:
            logger.error(
                f"题库返回的答案数量（{len(answers)}）与题目数量（{total_questions}）不匹配，正在补齐或截断以防错位！"
            )
            answers = list(answers) + [None] * (total_questions - len(answers))
            answers = answers[:total_questions]

        for q, res in zip(question_items, answers):
            logger.debug(f"当前题目信息 -> {q}")
            answer = ""
            if not res:
                answer = random_answer(q["options"], q["type"])
                q[f'answerSource{q["id"]}'] = "random"
            else:
                answer = self._match_question_answer(q, res, origin_html)
                if not answer:
                    logger.warning(f"找到答案但答案未能匹配 -> {res}\t随机选择答案")
                    answer = random_answer(q["options"], q["type"])
                    q[f'answerSource{q["id"]}'] = "random"
                else:
                    logger.info(f"成功获取到答案：{answer}")
                    q[f'answerSource{q["id"]}'] = "cover"
                    found_answers += 1

            q["answerField"][f'answer{q["id"]}'] = answer
            logger.info(f'{q["title"]} 填写答案为 {answer}')

        cover_rate = (found_answers / total_questions) * 100 if total_questions else 0.0
        logger.info(f"章节检测题库覆盖率： {cover_rate:.0f}%")
        return total_questions, cover_rate

    def _build_work_submit_payload(self, questions: dict, cover_rate: float) -> dict:
        """根据提交参数与覆盖率决定 pyFlag，并展平题目作答字段生成提交表单."""
        # 提交模式 现在与题库绑定, 留空直接提交, 1保存但不提交
        if self.tiku.get_submit_params() == "1":
            questions["pyFlag"] = "1"
        elif self._is_manual_tiku() or cover_rate >= self.tiku.COVER_RATE * 100 or self.rollback_times >= 1:
            questions["pyFlag"] = ""
        else:
            questions["pyFlag"] = "1"
            logger.info(f"章节检测题库覆盖率低于{self.tiku.COVER_RATE * 100:.0f}%，不予提交")

        save_only = questions["pyFlag"] == "1"
        for q in questions["questions"]:
            qid = q["id"]
            ans_val = q["answerField"][f"answer{qid}"]
            if save_only and q.get(f"answerSource{qid}") != "cover":
                ans_val = ""
            questions.update(
                {
                    f"answer{qid}": ans_val,
                    f"answertype{qid}": q["answerField"][f"answertype{qid}"],
                }
            )

        del questions["questions"]
        return questions

    def _submit_work_form(self, session, payload: dict) -> bool:
        """提交或暂存测验作答表单."""
        res = session.post(
            "https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNew",
            data=payload,
            headers=WORK_SUBMIT_HEADERS,
        )
        action = "提交" if payload["pyFlag"] == "" else "保存"
        if res.status_code == 200:
            res_json = res.json()
            if res_json["status"]:
                logger.info(f'{action}答题成功 -> {res_json["msg"]}')
                return True
            logger.error(f'{action}答题失败 -> {res_json["msg"]}')
            return False
        logger.error(f"{action}答题失败 -> {res.text}")
        return False

    def _evaluate_work_submission(
        self,
        session,
        course: dict,
        job: dict,
        job_info: dict,
        payload: dict,
        attempt: int,
        max_retries: int,
        total_questions: int,
    ) -> tuple[Optional[StudyResult], Optional[list], Optional[float]]:
        """校验提交后的作答成绩与错题，返回 (终结状态, 错题反馈, 本轮成绩)."""
        if payload["pyFlag"] == "1":
            # 仅保存未提交，无法判断成绩，保持原有行为
            return StudyResult.SUCCESS, None, None

        result_info = self._check_work_result(session, course, job, job_info, payload)
        if result_info is None:
            # 无法获取成绩详情（如接口异常），按原行为返回成功，避免误判失败
            return StudyResult.SUCCESS, None, None

        score = float(result_info.get("score", 0.0) or 0.0)
        unknown = int(result_info.get("unknown", 0) or 0)
        if result_info.get("all_correct", False):
            logger.info(f"章节检测全部正确（成绩 {score} 分），通过！")
            return StudyResult.SUCCESS, None, score
        if score >= 99.95:
            # 逐题比对存在格式差异或解析失配, 但满分成绩说明实际全对, 以分数为准
            if unknown > 0:
                logger.warning(
                    f"成绩 {score} 分达到满分, 以分数为准通过"
                    f"（{unknown} 题答案字段未能解析, 建议人工复核）"
                )
            else:
                logger.info(f"逐题比对存在格式差异, 但成绩 {score} 分达到满分, 以分数为准, 通过！")
            return StudyResult.SUCCESS, None, score
        if unknown > 0:
            # 解析失配且未达满分: 判定不可信, 不触发重做, 保留已提交成绩
            logger.warning(f"{unknown} 题答案字段解析失败且成绩 {score} 分未达满分, 跳过重做判定")
            return StudyResult.SUCCESS, None, score

        feedback = result_info.get("feedback", [])
        wrong_count = len(feedback)
        if attempt >= max_retries:
            # 已是最后一轮(含单轮模式), 保留已提交成绩, 不再触发无意义的重做
            logger.warning(
                f"章节检测有 {wrong_count}/{total_questions} 题回答错误（成绩 {score} 分），"
                f"已保留本次成绩, 请人工检查处理"
            )
            return StudyResult.SUCCESS, feedback, score

        logger.warning(
            f"章节检测有 {wrong_count}/{total_questions} 题回答错误（成绩 {score} 分），"
            f"已将错误反馈给AI，准备重新作答提交 (第 {attempt + 1}/{max_retries + 1} 轮)"
        )
        return None, feedback, score

    def study_work(self, _course, _job, _job_info) -> StudyResult:
        if not self.tiku or self.tiku.DISABLE:
            return StudyResult.SUCCESS

        _session = SessionManager.get_session()
        max_retries = self._resolve_work_redo_retries()
        query_delay = self.kwargs.get("query_delay", 0)
        feedback_history = None
        last_submitted_score = None

        for attempt in range(max_retries + 1):
            if attempt > 0:
                logger.warning(
                    f"章节检测重做第 {attempt}/{max_retries} 轮，携带上一轮错误反馈重新作答"
                )
                time.sleep(2)

            # 1. 获取题目
            try:
                final_resp, questions = self._fetch_work_questions(_session, _course, _job, _job_info)
            except PermissionError as e:
                logger.warning(f"跳过章节检测: {e}")
                return StudyResult.SUCCESS
            except Exception as e:
                if attempt > 0:
                    logger.error(
                        f"重做轮无法获取题目(上一轮提交成绩 {last_submitted_score} 分), "
                        f"该课程可能仅允许作答一次: {e}"
                    )
                else:
                    logger.error(f"获取章节检测题目失败, 达到最大重试次数: {e}")
                return StudyResult.ERROR

            # 2. 查题并填充作答字段
            origin_html = final_resp.text  # 用于配合输出网页源码, 帮助修复#391错误
            total_questions, cover_rate = self._query_and_fill_work_answers(
                questions,
                origin_html,
                query_delay=query_delay,
                feedback_history=feedback_history,
            )

            # 3. 组建并提交表单
            payload = self._build_work_submit_payload(questions, cover_rate)
            if not self._submit_work_form(_session, payload):
                return StudyResult.ERROR

            # 4. 校验成绩并决定是否携带错题反馈重做
            final_result, feedback_history, last_submitted_score = self._evaluate_work_submission(
                _session,
                _course,
                _job,
                _job_info,
                payload,
                attempt=attempt,
                max_retries=max_retries,
                total_questions=total_questions,
            )
            if final_result is not None:
                return final_result

            self.rollback_times += 1

        # 达到最大重试次数仍未全对
        logger.error(f"章节检测重试 {max_retries + 1} 次仍未全部正确，请人工检查处理")
        return StudyResult.ERROR

    def _check_work_result(self, _session, _course, _job, _job_info, questions) -> Optional[dict]:
        """
        章节检测提交后，查询最新一次作答的成绩与对错详情，供判断是否需要重做。

        Args:
            _session: 当前会话
            _course: 课程信息
            _job: 任务点信息
            questions: 提交时使用的表单数据（含 workId / workAnswerId 等）

        Returns:
            {"all_correct": bool, "feedback": list[str], "score": float, "times": int}
            或 None（无法获取成绩详情时返回 None）
        """
        work_id = str(
            questions.get("workId", "")
            or questions.get("workRelationId", "")
            or _job["jobid"].replace("work-", "")
        )
        work_answer_id = str(questions.get("workAnswerId", "") or "")
        course_id = str(_course.get("courseId", ""))
        class_id = str(_course.get("clazzId", ""))
        cpi = str(_course.get("cpi", "") or questions.get("cpi", ""))

        # 1. 获取作答记录列表（提交后服务端异步生成记录，需稍作等待并多次重试）
        records = None
        for attempt in range(5):
            try:
                resp = _session.get(
                    "https://mooc1.chaoxing.com/mooc-ans/work/record-list",
                    params={
                        "courseId": course_id,
                        "classId": class_id,
                        "workId": work_id,
                        "workAnswerId": work_answer_id,
                        "cpi": cpi,
                        "api": "1",
                        "mooc2": "1",
                        "ut": "s",
                    },
                    timeout=20,
                )
                records = _parse_work_record_list(resp.text)
                if records:
                    break
            except Exception as e:
                logger.warning(f"获取章节检测作答记录失败 (第{attempt + 1}次): {e}")
            if attempt < 4:
                time.sleep(1.5)

        if not records:
            # 兜底：重新访问题目页判断是否已通过（详情页=已提交有成绩；可编辑页=未通过可重做）
            logger.warning("无法获取章节检测作答记录，尝试通过题目页状态判断")
            try:
                resp = _session.get(
                    "https://mooc1.chaoxing.com/mooc-ans/api/work",
                    params={
                        "api": "1",
                        "workId": _job["jobid"].replace("work-", ""),
                        "jobid": _job["jobid"],
                        "originJobId": _job["jobid"],
                        "needRedirect": "true",
                        "skipHeader": "true",
                        "knowledgeid": str(_job_info.get("knowledgeid", "") or _job.get("knowledgeid", "")),
                        "ktoken": str(_job_info.get("ktoken", "") or _job.get("ktoken", "")),
                        "cpi": str(_job_info.get("cpi", "") or _job.get("cpi", "") or cpi),
                        "ut": "s",
                        "clazzId": class_id,
                        "type": "",
                        "enc": str(_job.get("enc", "")),
                        "mooc2": "1",
                        "courseid": course_id,
                    },
                    timeout=20,
                )
                html = resp.text
                if "answerwqbid" in html:
                    # 可编辑页面：说明未全部正确，可重新作答（该判定为页面状态推断, 未核对实际成绩）
                    logger.warning("题目页仍可编辑, 推断章节检测未全部正确(未核对成绩)")
                    return {
                        "all_correct": False,
                        "feedback": [],
                        "score": 0.0,
                        "times": 0,
                    }
                elif "正确答案" in html and "我的答案" in html:
                    # 已提交详情页：解析成绩与对错
                    detail = _parse_work_record_detail(html)
                    if detail:
                        all_correct, feedback, unknown = _summarize_work_detail(detail)
                        m = re.search(r"本次成绩<i>([\d.]+)</i>分", html)
                        score = float(m.group(1)) if m else 0.0
                        return {
                            "all_correct": all_correct,
                            "feedback": feedback,
                            "score": score,
                            "times": 0,
                            "unknown": unknown,
                        }
                return None
            except Exception as e:
                logger.warning(f"兜底判断章节检测状态失败: {e}")
                return None

        latest_times = max(r[0] for r in records)
        latest_score = dict(records).get(latest_times, 0.0)

        # 2. 获取最新一次作答详情（含每道题对错与正确答案）
        try:
            resp = _session.get(
                "https://mooc1.chaoxing.com/mooc-ans/work/record-detail",
                params={
                    "courseId": course_id,
                    "classId": class_id,
                    "workId": work_id,
                    "workAnswerId": work_answer_id,
                    "times": str(latest_times),
                    "cpi": cpi,
                    "ut": "s",
                    "isdisplaytable": "0",
                    "firstHeader": "2",
                    "isWork": "false",
                    "workSystem": "0",
                    "api": "1",
                    "archive": "false",
                    "mooc2": "1",
                },
                timeout=20,
            )
            detail = _parse_work_record_detail(resp.text)
        except Exception as e:
            logger.warning(f"获取章节检测作答详情失败: {e}")
            return None

        if not detail:
            logger.warning("章节检测作答详情解析为空，跳过成绩检查")
            return None

        # 3. 逐题判断对错，收集错误反馈
        all_correct, feedback, unknown = _summarize_work_detail(detail)

        logger.debug(
            f"章节检测成绩: {latest_score} 分, 全部正确: {all_correct}, "
            f"错题数: {len(feedback)}, 未解析题数: {unknown}"
        )
        return {
            "all_correct": all_correct,
            "feedback": feedback,
            "score": latest_score,
            "times": latest_times,
            "unknown": unknown,
        }
