#!/usr/bin/env python3
"""生成确定性的种子数据库，供冒烟测试与 CI 使用。

真实数据需要访问 GitHub，同步一次要 5–10 分钟，不适合放进 CI。
这里构造一份体积很小但结构完整的库：覆盖单课程仓、多课程仓（子课程别名）、
教师与评价、成绩构成、资料文件树、培养方案，以及昵称表命中场景。

用法::

    python scripts/seed_db.py --out /tmp/hoa-seed.db
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hoa_api.db import Store  # noqa: E402

COURSES = [
    {
        "code": "AUTO3005",
        "repo": "AUTO3005",
        "course_code": "AUTO3005",
        "name": "机器人学导论",
        "description": "旋量理论体系与机器人运动学建模。",
        "repo_type": "normal",
        "aliases": ["AUTO3005", "机器人学"],
        "teachers": ["楼云江", "杜惠"],
        "sections": [
            {"title": "教材", "items": [{"content": "《机器人学导论》", "author": None}]},
            {"title": "考核方式", "items": [{"content": "平时 30% · 期末 70%", "author": None}]},
        ],
        "lecturers": {
            "intro": [],
            "items": [{"name": "楼云江", "reviews": [{"content": "讲得清楚", "like": 3}]}],
            "summary": [],
        },
        "grading": {},
        "readme_md": "# AUTO3005 机器人学导论\n\n本课程介绍机器人运动学。\n",
        "readme_toml": 'course_name = "机器人学导论"\ncourse_code = "AUTO3005"\nrepo_type = "normal"\n',
        "materials": [
            {"name": "exams", "type": "folder", "path": "exams", "parent": "", "size": None},
            {"name": "2025.pdf", "type": "file", "path": "exams/2025.pdf", "parent": "exams", "size": 1024},
        ],
        "teachers_index": [("楼云江", 1), ("杜惠", 1)],
        "grade": {
            "variants": {"default": []},
            "items": [{"name": "平时", "percent": "30%"}, {"name": "期末", "percent": "70%"}],
        },
    },
    {
        # 多课程仓：子课程名与子课程代码都在别名里
        "code": "EE30XX",
        "repo": "EE30XX",
        "course_code": "EE30XX",
        "name": "电气专业选修课",
        "description": "电气专业的选修课合集。",
        "repo_type": "multi-project",
        "aliases": ["EE30XX", "电气传动自动控制系统", "EE3004", "开关电源原理与设计"],
        "teachers": ["詹瀚林"],
        "sections": [{"title": "开设课程", "items": [{"content": "电气传动自动控制系统", "author": None}]}],
        "lecturers": {"intro": [], "items": [{"name": "詹瀚林", "reviews": []}], "summary": []},
        "grading": {},
        "readme_md": "# EE30XX 电气专业选修课\n",
        "readme_toml": (
            'course_name = "电气专业选修课"\n'
            'course_code = "EE30XX"\n'
            'repo_type = "multi-project"\n\n'
            "[[courses]]\nname = \"电气传动自动控制系统\"\ncode = \"EE3004\"\n"
        ),
        "materials": [],
        "teachers_index": [("詹瀚林", 1)],
        "grade": None,
    },
    {
        # 与 AUTO3005 一起命中「机器人」，用于验证兼容层忽略 limit
        "code": "MECH3060",
        "repo": "MECH3060",
        "course_code": "MECH3060",
        "name": "机器人学基础",
        "description": "机器人运动学与动力学基础。",
        "repo_type": "normal",
        "aliases": ["MECH3060"],
        "teachers": ["王亮"],
        "sections": [],
        "lecturers": {"intro": [], "items": [{"name": "王亮", "reviews": []}], "summary": []},
        "grading": {},
        "readme_md": "# MECH3060 机器人学基础\n",
        "readme_toml": 'course_name = "机器人学基础"\ncourse_code = "MECH3060"\n',
        "materials": [],
        "teachers_index": [("王亮", 1)],
        "grade": None,
    },
    {
        # 昵称表命中场景：「高数」→ 微积分
        "code": "MATH1001",
        "repo": "MATH1001",
        "course_code": "MATH1001",
        "name": "微积分",
        "description": "一元与多元微积分。",
        "repo_type": "normal",
        "aliases": ["MATH1001"],
        "teachers": ["李文彬"],
        "sections": [],
        "lecturers": {"intro": [], "items": [{"name": "李文彬", "reviews": []}], "summary": []},
        "grading": {},
        "readme_md": "# MATH1001 微积分\n",
        "readme_toml": 'course_name = "微积分"\ncourse_code = "MATH1001"\n',
        "materials": [],
        "teachers_index": [("李文彬", 1)],
        "grade": None,
    },
]

PLAN = {
    "year": "2022",
    "major": "自动化",
    "major_code": "自动化",
    "school_name": "哈尔滨工业大学（深圳）",
    "study_level": "undergrad",
    "courses": [
        {
            "course_code": "AUTO3005",
            "course_name": "机器人学导论",
            "credit": 3.0,
            "assessment_method": "考试",
            "course_nature": "必修",
            "recommended_semester": "junior-autumn",
            "hours": 48,
        },
        {
            "course_code": "MATH1001",
            "course_name": "微积分",
            "credit": 5.0,
            "assessment_method": "考试",
            "course_nature": "必修",
            "recommended_semester": "fresh-autumn",
            "hours": 80,
        },
    ],
}


def build(db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()
    store = Store(str(db_path))
    for course in COURSES:
        payload = {k: v for k, v in course.items() if k not in ("teachers_index", "grade")}
        payload.setdefault("source_commit", "seed")
        payload.setdefault("source_updated", "2026-01-01T00:00:00Z")
        payload.setdefault("synced_at", "2026-01-01T00:00:00Z")
        store.upsert_course(payload)
        if payload["materials"]:
            store.replace_materials(payload["code"], payload["materials"])
        if course["teachers_index"]:
            store.replace_teachers(payload["code"], course["teachers_index"])
        if course["grade"]:
            store.upsert_grade(payload["code"], course["grade"])
    store.upsert_plan("2022", "自动化", "自动化", PLAN)
    store.commit()
    store.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="生成冒烟测试用的种子数据库")
    parser.add_argument("--out", default="/tmp/hoa-seed.db", help="输出数据库路径")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    build(out)
    print(f"✓ 种子库已生成: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
