"""存储层与检索打分测试。"""

from __future__ import annotations

import pytest

from hoa_api.db import Store


@pytest.fixture()
def store(tmp_path):
    store = Store(tmp_path / "test.db")
    store.upsert_course(
        {
            "code": "AUTO3005",
            "repo": "AUTO3005",
            "name": "机器人学导论",
            "description": "旋量理论",
            "repo_type": "normal",
            "aliases": ["机器人学"],
            "teachers": ["楼云江", "杜惠"],
            "sections": [],
            "lecturers": {},
            "grading": {},
            "readme_md": "# AUTO3005",
            "readme_toml": 'course_name = "机器人学导论"',
            "source_commit": "abc123",
            "source_updated": "2026-10-14T00:00:00Z",
            "synced_at": "2026-11-06T00:00:00Z",
            "materials": [],
        }
    )
    store.replace_materials(
        "AUTO3005",
        [
            {"name": "exams", "type": "folder", "path": "exams", "parent": "", "size": None},
            {
                "name": "2025.pdf",
                "type": "file",
                "path": "exams/2025.pdf",
                "parent": "exams",
                "size": 1024,
            },
        ],
    )
    store.replace_teachers("AUTO3005", [("楼云江", 2), ("杜惠", 1)])
    store.upsert_grade("AUTO3005", {"variants": {"default": []}, "items": []})
    store.commit()
    return store


def test_get_course_by_code_and_repo(store):
    assert store.get_course("AUTO3005")["name"] == "机器人学导论"
    assert store.get_course("auto3005")["name"] == "机器人学导论"
    assert store.get_course_by_repo("AUTO3005")["code"] == "AUTO3005"
    assert store.get_course("NOPE") is None


def test_search_by_keyword_variants(store):
    assert store.search_courses(keyword="AUTO3005")[0]["code"] == "AUTO3005"
    assert store.search_courses(keyword="机器人")[0]["code"] == "AUTO3005"
    assert store.search_courses(keyword="楼云江")[0]["code"] == "AUTO3005"
    assert store.search_courses(keyword="不存在的课程") == []


def test_search_by_teacher(store):
    results = store.search_courses(teacher="楼云江")
    assert results[0]["code"] == "AUTO3005"
    assert store.search_courses(teacher="不存在") == []


def test_materials_tree(store):
    root = store.get_materials("AUTO3005")
    assert [node["name"] for node in root] == ["exams"]
    children = store.get_materials("AUTO3005", "exams")
    assert children[0]["path"] == "exams/2025.pdf"
    assert children[0]["size"] == 1024


def test_teachers(store):
    teachers = store.list_teachers(keyword="楼")
    assert teachers[0]["name"] == "楼云江"
    assert teachers[0]["courses"] == ["AUTO3005"]
    assert teachers[0]["review_count"] == 2
    assert store.list_teachers(course="AUTO3005")


def test_counts(store):
    assert store.count_courses() == 1
    assert store.count_teachers() == 2
    assert store.count_materials() == 2
