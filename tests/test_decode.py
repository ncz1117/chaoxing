# -*- coding: utf-8 -*-
"""PR10 回归测试：api.decode 脱敏 HTML/JSON 样本解析与字体解密分支."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api.decode import (  # noqa: E402
    decode_course_card,
    decode_course_folder,
    decode_course_list,
    decode_course_point,
    decode_questions_info,
)


class DecodeTestCase(unittest.TestCase):
    def test_decode_course_list_parses_open_and_skips_not_open(self):
        html = """
        <html><body>
          <div class="course" id="c-open-1" info="info-1" roleid="1">
            <input class="clazzId" value="cls101" />
            <input class="courseId" value="crs201" />
            <a href="/visit/stucoursemiddle?courseid=crs201&cpi=9988&ut=s"></a>
            <span class="course-name" title="高等数学">高等数学</span>
            <p class="margint10" title="必修课程简介"></p>
            <p class="color3" title="张老师"></p>
          </div>
          <div class="course" id="c-open-2" info="info-2" roleid="2">
            <input class="clazzId" value="cls102" />
            <input class="courseId" value="crs202" />
            <a href="/visit/stucoursemiddle?cpi=7766&courseid=crs202"></a>
            <span class="course-name" title="线性代数">线性代数</span>
            <p class="color3" title="李老师"></p>
          </div>
          <div class="course" id="c-closed-a" info="info-3" roleid="1">
            <a class="not-open-tip">未开课</a>
          </div>
          <div class="course" id="c-closed-d" info="info-4" roleid="1">
            <div class="not-open-tip">已结课</div>
          </div>
        </body></html>
        """
        courses = decode_course_list(html)
        self.assertEqual(len(courses), 2)
        self.assertEqual(
            courses[0],
            {
                "id": "c-open-1",
                "info": "info-1",
                "roleid": "1",
                "clazzId": "cls101",
                "courseId": "crs201",
                "cpi": "9988",
                "title": "高等数学",
                "desc": "必修课程简介",
                "teacher": "张老师",
            },
        )
        self.assertEqual(courses[1]["courseId"], "crs202")
        self.assertEqual(courses[1]["cpi"], "7766")
        self.assertEqual(courses[1]["desc"], "")

    def test_decode_course_folder_parses_fileid_items_and_skips_invalid(self):
        html = """
        <ul class="file-list">
          <li fileid="1001"><input class="rename-input" value="默认文件夹" /></li>
          <li><input class="rename-input" value="无fileid" /></li>
          <li fileid=""><input class="rename-input" value="空fileid" /></li>
          <li fileid="1002"><input class="rename-input" value="归档课程" /></li>
        </ul>
        """
        folders = decode_course_folder(html)
        self.assertEqual(
            folders,
            [
                {"id": "1001", "rename": "默认文件夹"},
                {"id": "1002", "rename": "归档课程"},
            ],
        )

    def test_decode_course_point_extracts_status_and_locked_flag(self):
        locked_html = """
        <div class="chapter_unit">
          <ul>
            <li>
              <div id="cur10001">
                <a class="clicktitle">\n  第一章\n  导论  </a>
                <input class="knowledgeJobCount" value="2" />
                <span class="bntHoverTips">待完成</span>
              </div>
            </li>
            <li>
              <div id="cur10002">
                <a class="clicktitle">第二章 进阶</a>
                <span class="bntHoverTips">已完成</span>
              </div>
            </li>
            <li>
              <div class="no-id-node"><a class="clicktitle">无效节点</a></div>
            </li>
          </ul>
        </div>
        <div class="chapter_unit">
          <ul>
            <li>
              <div id="cur10003">
                <a class="clicktitle">第三章 测验</a>
                <span class="bntHoverTips">章节解锁中</span>
              </div>
            </li>
          </ul>
        </div>
        """
        parsed = decode_course_point(locked_html)
        self.assertTrue(parsed["hasLocked"])
        self.assertEqual(len(parsed["points"]), 3)
        self.assertEqual(
            parsed["points"][0],
            {
                "id": "10001",
                "title": "第一章  导论",
                "jobCount": "2",
                "has_finished": False,
                "need_unlock": False,
            },
        )
        self.assertEqual(parsed["points"][1]["jobCount"], 1)
        self.assertTrue(parsed["points"][1]["has_finished"])
        self.assertFalse(parsed["points"][1]["need_unlock"])
        self.assertTrue(parsed["points"][2]["need_unlock"])

        unlocked_html = """
        <div class="chapter_unit">
          <ul>
            <li>
              <div id="cur20001">
                <a class="clicktitle">单一开放章节</a>
                <span class="bntHoverTips">已完成</span>
              </div>
            </li>
          </ul>
        </div>
        """
        unlocked = decode_course_point(unlocked_html)
        self.assertFalse(unlocked["hasLocked"])
        self.assertEqual(len(unlocked["points"]), 1)

    def test_decode_course_card_not_open_empty_and_mixed_attachments(self):
        self.assertEqual(decode_course_card("<div>章节未开放，暂不可学习</div>"), ([], {"notOpen": True}))
        self.assertEqual(decode_course_card("<html><body>plain page</body></html>"), ([], {}))

        marg_obj = {
            "defaults": {
                "ktoken": "kt-1",
                "mtEnc": "mt-2",
                "reportTimeInterval": 60,
                "defenc": "df-3",
                "cardid": "cd-4",
                "cpi": "7788",
                "qnenc": "qn-5",
                "knowledgeid": "9900",
            },
            "attachments": [
                {
                    "type": "video",
                    "isPassed": True,
                    "job": True,
                    "jobid": "v-passed",
                    "mid": "m0",
                    "objectId": "obj0",
                },
                {
                    "type": "video",
                    "isPassed": False,
                    "job": True,
                    "jobid": "v-1",
                    "otherInfo": "nodeId_9900-1&courseId=1001",
                    "mid": "mid-v1",
                    "objectId": "obj-v1",
                    "aid": "aid-v1",
                    "playTime": 12000,
                    "attDuration": "10",
                    "attDurationEnc": "att-enc",
                    "videoFaceCaptureEnc": "face-enc",
                    "property": {"name": "第一节视频", "rt": "0.9"},
                },
                {
                    "type": "video",
                    "isPassed": False,
                    "job": True,
                    "jobid": "v-bad",
                    "objectId": "obj-bad",
                    "property": {"name": "转码失败视频"},
                },
                {
                    "type": "document",
                    "isPassed": False,
                    "job": True,
                    "jobid": "doc-1",
                    "otherInfo": "nodeId_9900-2&extra=1",
                    "jtoken": "jt-doc",
                    "mid": "mid-doc",
                    "enc": "enc-doc",
                    "aid": "aid-doc",
                    "property": {"objectid": "obj-doc"},
                },
                {
                    "type": "workid",
                    "isPassed": False,
                    "job": True,
                    "jobid": "work-123",
                    "otherInfo": "nodeId_9900-3&foo=bar",
                    "mid": "mid-w",
                    "enc": "enc-w",
                    "aid": "aid-w",
                },
                {
                    "type": "video",
                    "isPassed": False,
                    "job": True,
                    "jobid": "live-1",
                    "otherInfo": "nodeId_9900-4&live=1",
                    "mid": "mid-live",
                    "objectId": "obj-live",
                    "aid": "aid-live",
                    "property": {"title": "直播回放", "liveId": "L100", "streamName": "streamA"},
                },
                {
                    "type": "read",
                    "isPassed": False,
                    "job": None,
                    "jobid": "read-1",
                    "jtoken": "jt-r1",
                    "mid": "mid-r1",
                    "otherInfo": "other-r1",
                    "enc": "enc-r1",
                    "aid": "aid-r1",
                    "property": {"title": "拓展阅读", "id": "rid-1", "read": False},
                },
                {
                    "type": "read",
                    "isPassed": False,
                    "job": None,
                    "jobid": "read-done",
                    "property": {"title": "已读阅读", "id": "rid-2", "read": True},
                },
                {
                    "type": "flash",
                    "isPassed": False,
                    "job": True,
                    "jobid": "unknown-1",
                },
            ],
        }
        html = f"<script>var mArg = {json.dumps(marg_obj, ensure_ascii=False)};</script>"
        jobs, info = decode_course_card(html)
        self.assertEqual(info["ktoken"], "kt-1")
        self.assertEqual(info["knowledgeid"], "9900")
        self.assertEqual([j["type"] for j in jobs], ["video", "document", "workid", "live", "read"])
        self.assertEqual(jobs[0]["otherinfo"], "nodeId_9900-1")
        self.assertEqual(jobs[0]["name"], "第一节视频")
        self.assertEqual(jobs[1]["objectid"], "obj-doc")
        self.assertEqual(jobs[2]["jobid"], "work-123")
        self.assertEqual(jobs[3]["liveId"], "L100")
        self.assertEqual(jobs[3]["streamName"], "streamA")
        self.assertEqual(jobs[4]["title"], "拓展阅读")

    def test_decode_questions_info_unencrypted_and_font_encrypted(self):
        unencrypted_html = """
        <html><body>
          <form>
            <input name="workId" value="9001" />
            <input name="cpi" value="888" />
            <input name="answer101" value="ignored" />
            <input value="no-name-ignored" />

            <div class="singleQuesId" data="101">
              <div class="TiMu" data="0">
                <div class="Zy_TItle">1+1等于<img src="https://img.example/q.png" />？</div>
                <ul>
                  <li aria-label="B. 错误选择">B. 错误</li>
                  <li aria-label="A. 正确选择">A. 正确</li>
                </ul>
              </div>
            </div>

            <div class="singleQuesId" data="102">
              <div class="TiMu" data="1">
                <div class="Zy_TItle">多选题干</div>
                <ul>
                  <li>B 选项二</li>
                  <li>A 选项一选择</li>
                </ul>
              </div>
            </div>

            <div class="singleQuesId" data="103">
              <div class="TiMu" data="2">
                <div class="Zy_TItle">填空题干</div>
              </div>
            </div>

            <div class="singleQuesId" data="104">
              <div class="TiMu" data="3">
                <div class="Zy_TItle">判断题干</div>
                <ul>
                  <li>A 对</li>
                  <li>B 错</li>
                </ul>
              </div>
            </div>

            <div class="singleQuesId" data="105">
              <div class="TiMu" data="99">
                <div class="Zy_TItle">扩展题型</div>
              </div>
            </div>
          </form>
        </body></html>
        """
        with patch("api.decode.logger"):
            data = decode_questions_info(unencrypted_html)

        self.assertEqual(data["workId"], "9001")
        self.assertEqual(data["cpi"], "888")
        self.assertNotIn("answer101", data)
        self.assertEqual(data["answerwqbid"], "101,102,103,104,105,")
        self.assertEqual(len(data["questions"]), 5)

        q1, q2, q3, q4, q5 = data["questions"]
        self.assertEqual(q1["type"], "single")
        self.assertEqual(q1["title"], '1+1等于<img src="https://img.example/q.png">？')
        self.assertEqual(q1["options"], "A. 正确\nB. 错误")
        self.assertEqual(q2["type"], "multiple")
        self.assertEqual(q2["options"], "A 选项一\nB 选项二")
        self.assertEqual(q3["type"], "completion")
        self.assertEqual(q3["options"], "")
        self.assertEqual(q4["type"], "judgement")
        self.assertEqual(q5["type"], "unknown")

        encrypted_html = """
        <html>
          <head><style id="cxSecretStyle">@font-face{font-family:cx;}</style></head>
          <body>
            <form>
              <div class="singleQuesId" data="201">
                <div class="TiMu" data="0">
                  <div class="Zy_TItle">密文题干</div>
                  <ul><li aria-label="A. 密文选项">A. 密文选项</li></ul>
                </div>
              </div>
            </form>
          </body>
        </html>
        """
        with patch("api.decode.FontDecoder") as mock_decoder_cls:
            mock_decoder_cls.return_value.decode.side_effect = lambda s: f"DEC:{s}"
            enc_data = decode_questions_info(encrypted_html)

        mock_decoder_cls.assert_called_once_with(encrypted_html)
        self.assertEqual(enc_data["questions"][0]["title"], "DEC:密文题干")
        self.assertEqual(enc_data["questions"][0]["options"], "DEC:A. 密文选项")


if __name__ == "__main__":
    unittest.main()
