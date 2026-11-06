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


def test_search_matches_readme_body(tmp_path):
    """正文命中：与老 course-server 的 GitHub 代码检索兜底行为保持一致。

    老实现在本地缓存未命中时会回落到 GitHub code search，因此像
    「线性代数」这种只出现在 readme 正文、子课程名里的关键词同样能命中课程。
    新服务直接用已同步下来的 readme 正文匹配，无需再消耗 GitHub API 配额。
    """
    store = Store(tmp_path / "body.db")
    store.upsert_course(
        {
            "code": "COMP2010",
            "repo": "COMP2010",
            "name": "近世代数",
            "description": "",
            "repo_type": "normal",
            "aliases": [],
            "teachers": ["唐珑珑"],
            "sections": [],
            "lecturers": {},
            "grading": {},
            "readme_md": "本课程前修要求：线性代数",
            "readme_toml": 'course_name = "近世代数"\n[[courses]]\nname = "线性代数复习"',
            "source_commit": "abc123",
            "source_updated": "2026-10-14T00:00:00Z",
            "synced_at": "2026-11-06T00:00:00Z",
            "materials": [],
        }
    )
    store.commit()

    assert store.search_courses(keyword="线性代数")[0]["code"] == "COMP2010"
    # 正文命中排在课程名命中之后
    store.upsert_course(
        {
            "code": "AUTO3005",
            "repo": "AUTO3005",
            "name": "线性代数",
            "description": "",
            "repo_type": "normal",
            "aliases": [],
            "teachers": [],
            "sections": [],
            "lecturers": {},
            "grading": {},
            "readme_md": "",
            "readme_toml": "",
            "source_commit": "abc123",
            "source_updated": "2026-10-14T00:00:00Z",
            "synced_at": "2026-11-06T00:00:00Z",
            "materials": [],
        }
    )
    store.commit()
    codes = [item["code"] for item in store.search_courses(keyword="线性代数")]
    assert codes[0] == "AUTO3005"
    assert "COMP2010" in codes


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


def test_course_identity_is_repo_not_toml_code(tmp_path):
    """回归：课程身份必须以仓库 ID 为准。

    真实案例：``MATH1005K`` 仓的 readme.toml 里写的是 ``course_code = "MATH1005"``，
    若以它作主键会与真正的 ``MATH1005`` 仓互相覆盖，导致 8 门课凭空消失。
    """
    store = Store(tmp_path / "ident.db")
    for repo, toml_code, name in (
        ("MATH1005", "MATH1005", "复变函数与积分变换"),
        ("MATH1005K", "MATH1005", "复变函数与积分变换(K班)"),
    ):
        store.upsert_course(
            {
                "code": repo,
                "repo": repo,
                "course_code": toml_code,
                "name": name,
                "description": "",
                "repo_type": "normal",
                "aliases": [toml_code],
                "teachers": [],
                "sections": [],
                "lecturers": {},
                "grading": {},
                "readme_md": "",
                "readme_toml": "",
                "source_commit": None,
                "source_updated": None,
                "synced_at": "2026-11-06T00:00:00Z",
                "materials": [],
            }
        )
    store.commit()

    assert store.count_courses() == 2
    assert store.get_course("MATH1005K")["repo"] == "MATH1005K"
    assert store.get_course("MATH1005")["repo"] == "MATH1005"
    # 别名可解析，但不得改变身份
    assert store.get_course_by_alias("MATH1005")["repo"] == "MATH1005"
    store.close()


def test_search_matches_toml_course_code(tmp_path):
    store = Store(tmp_path / "search.db")
    store.upsert_course(
        {
            "code": "ELEC2102K",
            "repo": "ELEC2102K",
            "course_code": "ELEC2102k",
            "name": "概率和数理统计",
            "description": "",
            "repo_type": "normal",
            "aliases": ["ELEC2102k"],
            "teachers": [],
            "sections": [],
            "lecturers": {},
            "grading": {},
            "readme_md": "",
            "readme_toml": "",
            "source_commit": None,
            "source_updated": None,
            "synced_at": "2026-11-06T00:00:00Z",
            "materials": [],
        }
    )
    store.commit()
    assert store.search_courses(keyword="ELEC2102K")[0]["code"] == "ELEC2102K"
    assert store.search_courses(keyword="ELEC2102k")[0]["code"] == "ELEC2102K"
    store.close()
