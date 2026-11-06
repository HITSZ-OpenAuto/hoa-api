"""`readme.toml` 解析与规范化测试。"""

from __future__ import annotations

from hoa_api.course_data import (
    normalize_lecturers,
    normalize_sections,
    parse_course_toml,
    parse_grading_payload,
    parse_plan_toml,
)
from hoa_api.nicknames import resolve_nickname

SAMPLE = """
course_name = "机器人学导论"
course_code = "AUTO3005"
repo_type = "normal"
description = \"\"\"
课程简介
\"\"\"

[lecturers]

[[lecturers.intro]]
content = "教师团队总体介绍"
author = { name = "管理员", date = "2025-01" }

[[lecturers.items]]
name = "楼云江"

[[lecturers.items.reviews]]
content = "会细致推导公式"
author = { name = "昵称", link = "https://github.com/xxx", date = "2025-03" }

[[lecturers.items]]
name = "杜惠"

[[lecturers.summary]]
content = "建议尽早选课"

[[sections]]
title = "教材与在线资源"

[[sections.items]]
content = "- 教材: 《书名》"
author = { name = "昵称B", date = "2024-01" }
"""


def test_parse_course_toml_basic_fields():
    parsed = parse_course_toml(SAMPLE)
    assert parsed["name"] == "机器人学导论"
    assert parsed["code"] == "AUTO3005"
    assert parsed["repo_type"] == "normal"
    assert "课程简介" in parsed["description"]


def test_parse_course_toml_lecturers():
    parsed = parse_course_toml(SAMPLE)
    lecturers = parsed["lecturers"]
    assert len(lecturers["items"]) == 2
    assert lecturers["items"][0]["name"] == "楼云江"
    assert lecturers["items"][0]["reviews"][0]["content"] == "会细致推导公式"
    assert lecturers["items"][0]["reviews"][0]["author"]["date"] == "2025-03"
    assert len(lecturers["intro"]) == 1
    assert len(lecturers["summary"]) == 1
    assert parsed["teachers"] == ["楼云江", "杜惠"]


def test_parse_course_toml_sections():
    parsed = parse_course_toml(SAMPLE)
    assert len(parsed["sections"]) == 1
    section = parsed["sections"][0]
    assert section["title"] == "教材与在线资源"
    assert section["items"][0]["author"]["name"] == "昵称B"


def test_parse_empty_toml_is_safe():
    parsed = parse_course_toml("")
    assert parsed["name"] == ""
    assert parsed["teachers"] == []
    assert parsed["sections"] == []


def test_placeholder_values_are_treated_as_empty():
    """未填写内容的课程仓仍保持着模板原文，不能污染课程名与别名。"""
    parsed = parse_course_toml(
        """
course_name = "课程中文名称"
repo_type = "normal"
course_code = "CODE1234"
description = \"\"\"
在这里填写课程的简要介绍。
可以换行。
\"\"\"
"""
    )
    assert parsed["name"] == ""
    assert parsed["code"] == ""
    assert parsed["description"] == ""


def test_is_placeholder():
    from hoa_api.course_data import is_placeholder

    assert is_placeholder("CODE1234")
    assert is_placeholder("课程中文名称")
    assert is_placeholder("在这里填写课程的简要介绍。\n可以换行。")
    assert is_placeholder("")
    assert is_placeholder(None)
    assert not is_placeholder("机器人学导论")
    assert not is_placeholder("AUTO3005")


def test_normalize_lecturers_handles_garbage():
    result = normalize_lecturers({"items": ["not-a-dict", {"no_name": 1}, {"name": "A"}]})
    assert [item["name"] for item in result["items"]] == ["A"]


def test_normalize_sections_handles_garbage():
    assert normalize_sections("not-a-list") == []
    assert normalize_sections([{"items": []}])[0]["title"] == "未命名章节"


def test_parse_grading_payload_variants():
    payload = {
        "2021_default": [{"name": "作业", "percent": "10%"}],
        "default": [
            {"name": "作业", "percent": "10%"},
            {"name": "期末考试", "percent": "90%"},
        ],
    }
    result = parse_grading_payload(payload)
    assert result["items"][0]["name"] == "作业"
    assert len(result["items"]) == 2
    assert "2021_default" in result["variants"]


def test_parse_plan_toml():
    plan = parse_plan_toml(
        """
[info]
major_code = "030201"
major_name = "自动化"
year = "2022"

[[courses]]
course_code = "AUTO1001"
course_name = "自动化认知与实践"
credit = 4.0
recommended_year_semester = "第一学年秋季"

[courses.hours]
theory = 40
"""
    )
    assert plan["year"] == "2022"
    assert plan["major"] == "自动化"
    assert plan["major_code"] == "030201"
    assert plan["courses"][0]["course_code"] == "AUTO1001"
    assert plan["courses"][0]["hours"]["theory"] == 40


def test_sub_course_aliases_are_extracted():
    """多课程仓的子课程名与子课程代码应当进入别名。

    EE30XX 仓里用 [[courses]] 收纳「电气传动自动控制系统 / EE3004」等子课程，
    学生搜的是子课程名，老 course-server 也正是靠这些别名命中的。
    """
    parsed = parse_course_toml(
        """
course_name = "电气专业选修课"
course_code = "EE30XX"
repo_type = "multi-project"

[[courses]]
name = "电气传动自动控制系统"
code = "EE3004"

[[courses]]
name = "开关电源原理与设计"
code = "EE3011"
"""
    )
    assert "电气传动自动控制系统" in parsed["aliases"]
    assert "EE3004" in parsed["aliases"]
    assert "开关电源原理与设计" in parsed["aliases"]
    assert parsed["aliases"][0] == "EE30XX"


def test_resolve_nickname():
    assert resolve_nickname("高数") == "微积分"
    assert resolve_nickname("线性代数") == "代数"
    assert resolve_nickname("机器人学导论") == "机器人学导论"
    assert resolve_nickname("") == ""
