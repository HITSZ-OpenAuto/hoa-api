"""`readme.toml` 解析与规范化测试。"""

from __future__ import annotations

from hoa_api.course_data import (
    normalize_lecturers,
    normalize_sections,
    parse_course_toml,
    parse_grading_payload,
    parse_plan_toml,
)

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
