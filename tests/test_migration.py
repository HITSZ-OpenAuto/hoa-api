"""旧版本数据库的列迁移测试。"""

from __future__ import annotations

import sqlite3

from hoa_api.db import Store


def test_migration_adds_missing_column(tmp_path):
    """升级后打开旧库必须自动补列，否则写入会失败。"""
    db_path = tmp_path / "old.db"

    # 造一个缺少 course_code 列的旧库
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE courses (
            code TEXT PRIMARY KEY,
            repo TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            repo_type TEXT NOT NULL DEFAULT 'normal',
            aliases TEXT NOT NULL DEFAULT '[]',
            teachers TEXT NOT NULL DEFAULT '[]',
            credit REAL,
            assessment_method TEXT,
            course_nature TEXT,
            hours TEXT,
            sections TEXT NOT NULL DEFAULT '[]',
            lecturers TEXT NOT NULL DEFAULT '{}',
            grading TEXT NOT NULL DEFAULT '{}',
            readme_md TEXT NOT NULL DEFAULT '',
            readme_toml TEXT NOT NULL DEFAULT '',
            source_commit TEXT,
            source_updated TEXT,
            synced_at TEXT NOT NULL,
            has_materials INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    conn.commit()
    conn.close()

    store = Store(db_path)
    store.upsert_course(
        {
            "code": "AUTO3005",
            "repo": "AUTO3005",
            "course_code": "AUTO3005",
            "name": "机器人学导论",
            "description": "",
            "repo_type": "normal",
            "aliases": [],
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
    assert store.count_courses() == 1
    assert store.get_course("AUTO3005")["course_code"] == "AUTO3005"
    store.close()
