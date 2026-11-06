"""SQLite 存储层：schema、写入与查询。

课程内容以 JSON 列存储（SQLite JSON1 并非所有构建都带），保证跨平台可移植；
155 门课的规模下无需更细的分表拆分。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS courses (
    code            TEXT PRIMARY KEY,
    repo            TEXT NOT NULL,
    course_code     TEXT NOT NULL DEFAULT '',
    name            TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    repo_type       TEXT NOT NULL DEFAULT 'normal',
    aliases         TEXT NOT NULL DEFAULT '[]',
    teachers        TEXT NOT NULL DEFAULT '[]',
    credit          REAL,
    assessment_method TEXT,
    course_nature   TEXT,
    hours           TEXT,
    sections        TEXT NOT NULL DEFAULT '[]',
    lecturers       TEXT NOT NULL DEFAULT '{}',
    grading         TEXT NOT NULL DEFAULT '{}',
    readme_md       TEXT NOT NULL DEFAULT '',
    readme_toml     TEXT NOT NULL DEFAULT '',
    source_commit   TEXT,
    source_updated  TEXT,
    synced_at       TEXT NOT NULL,
    has_materials   INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_courses_name ON courses(name);
CREATE INDEX IF NOT EXISTS idx_courses_repo ON courses(repo);

CREATE TABLE IF NOT EXISTS materials (
    course_code TEXT NOT NULL,
    path        TEXT NOT NULL,
    parent      TEXT NOT NULL DEFAULT '',
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,
    size        INTEGER,
    updated_at  TEXT,
    url         TEXT,
    PRIMARY KEY (course_code, path)
);

CREATE INDEX IF NOT EXISTS idx_materials_code ON materials(course_code);

CREATE TABLE IF NOT EXISTS teachers (
    name         TEXT NOT NULL,
    course_code  TEXT NOT NULL,
    review_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (name, course_code)
);

CREATE INDEX IF NOT EXISTS idx_teachers_name ON teachers(name);

CREATE TABLE IF NOT EXISTS grades (
    course_code TEXT PRIMARY KEY,
    payload     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
    year        TEXT NOT NULL,
    major       TEXT NOT NULL,
    major_code  TEXT,
    payload     TEXT NOT NULL,
    PRIMARY KEY (year, major)
);

CREATE TABLE IF NOT EXISTS repo_sync (
    repo       TEXT PRIMARY KEY,
    etag_toml  TEXT,
    etag_readme TEXT,
    etag_tree  TEXT,
    status     TEXT NOT NULL DEFAULT 'pending',
    error      TEXT,
    synced_at  TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


class Store:
    """所有数据库访问的唯一入口。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._plan_index: dict[str, list[tuple[str, str, str]]] | None = None
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """给已存在的旧版本库补齐新增列。

        ``CREATE TABLE IF NOT EXISTS`` 不会给已存在的表补列，
        升级时必须显式 ALTER，否则写入会以 "no such column" 失败。
        """
        migrations = {
            "courses": [
                ("course_code", "TEXT NOT NULL DEFAULT ''"),
            ],
        }
        for table, columns in migrations.items():
            existing = {
                row["name"]
                for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if not existing:
                continue
            for name, definition in columns:
                if name not in existing:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def close(self) -> None:
        self._conn.close()

    # ---------- meta ----------

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._conn.commit()

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    # ---------- courses ----------

    def upsert_course(self, course: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT INTO courses(
                code, repo, course_code, name, description, repo_type, aliases, teachers,
                credit, assessment_method, course_nature, hours, sections,
                lecturers, grading, readme_md, readme_toml, source_commit,
                source_updated, synced_at, has_materials
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(code) DO UPDATE SET
                repo=excluded.repo, course_code=excluded.course_code,
                name=excluded.name,
                description=excluded.description, repo_type=excluded.repo_type,
                aliases=excluded.aliases, teachers=excluded.teachers,
                credit=excluded.credit,
                assessment_method=excluded.assessment_method,
                course_nature=excluded.course_nature, hours=excluded.hours,
                sections=excluded.sections, lecturers=excluded.lecturers,
                grading=excluded.grading, readme_md=excluded.readme_md,
                readme_toml=excluded.readme_toml,
                source_commit=excluded.source_commit,
                source_updated=excluded.source_updated,
                synced_at=excluded.synced_at,
                has_materials=excluded.has_materials
            """,
            (
                course["code"],
                course["repo"],
                course.get("course_code", ""),
                course.get("name", ""),
                course.get("description", ""),
                course.get("repo_type", "normal"),
                _dumps(course.get("aliases", [])),
                _dumps(course.get("teachers", [])),
                course.get("credit"),
                course.get("assessment_method"),
                course.get("course_nature"),
                _dumps(course.get("hours")) if course.get("hours") else None,
                _dumps(course.get("sections", [])),
                _dumps(course.get("lecturers", {})),
                _dumps(course.get("grading", {})),
                course.get("readme_md", ""),
                course.get("readme_toml", ""),
                course.get("source_commit"),
                course.get("source_updated"),
                course["synced_at"],
                course.get("has_materials", 1 if course.get("materials") else 0),
            ),
        )

    def replace_materials(self, course_code: str, nodes: Iterable[dict[str, Any]]) -> None:
        self._conn.execute("DELETE FROM materials WHERE course_code = ?", (course_code,))
        rows = []
        for node in nodes:
            rows.append(
                (
                    course_code,
                    node.get("path", ""),
                    node.get("parent", ""),
                    node.get("name", ""),
                    node.get("type", "file"),
                    node.get("size"),
                    node.get("updated_at"),
                    node.get("url"),
                )
            )
        self._conn.executemany(
            "INSERT OR REPLACE INTO materials"
            "(course_code, path, parent, name, type, size, updated_at, url)"
            " VALUES(?,?,?,?,?,?,?,?)",
            rows,
        )

    def replace_teachers(self, course_code: str, teachers: list[tuple[str, int]]) -> None:
        self._conn.execute("DELETE FROM teachers WHERE course_code = ?", (course_code,))
        self._conn.executemany(
            "INSERT OR REPLACE INTO teachers(name, course_code, review_count) VALUES(?,?,?)",
            [(name, course_code, count) for name, count in teachers],
        )

    def commit(self) -> None:
        self._conn.commit()

    # ---------- queries ----------

    @staticmethod
    def _row_to_summary(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "code": row["code"],
            "course_code": row["course_code"],
            "name": row["name"],
            "aliases": _loads(row["aliases"], []),
            "teachers": _loads(row["teachers"], []),
            "repo": row["repo"],
            "url": f"https://github.com/{row['repo']}",
            "site_url": None,
            "credit": row["credit"],
            "updated_at": row["source_updated"],
        }

    @staticmethod
    def _row_to_course(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "code": row["code"],
            "course_code": row["course_code"],
            "name": row["name"],
            "description": row["description"],
            "aliases": _loads(row["aliases"], []),
            "teachers": _loads(row["teachers"], []),
            "repo": row["repo"],
            "url": f"https://github.com/{row['repo']}",
            "repo_type": row["repo_type"],
            "lecturers": _loads(row["lecturers"], {}),
            "sections": _loads(row["sections"], []),
            "grading": _loads(row["grading"], {}),
            "credit": row["credit"],
            "assessment_method": row["assessment_method"],
            "course_nature": row["course_nature"],
            "hours": _loads(row["hours"], None),
            "readme_md": row["readme_md"],
            "readme_toml": row["readme_toml"],
            "source": {
                "repo": row["repo"],
                "commit": row["source_commit"],
                "updated_at": row["source_updated"],
                "synced_at": row["synced_at"],
            },
            "has_materials": row["has_materials"],
            "updated_at": row["source_updated"],
        }

    def count_courses(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS c FROM courses").fetchone()["c"]

    def count_teachers(self) -> int:
        return self._conn.execute("SELECT COUNT(DISTINCT name) AS c FROM teachers").fetchone()["c"]

    def count_materials(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS c FROM materials").fetchone()["c"]

    def get_course(self, code: str) -> dict[str, Any] | None:
        """按课程 ID（仓库名）查询，大小写不敏感。"""
        row = self._conn.execute(
            "SELECT * FROM courses WHERE code = ? COLLATE NOCASE", (code,)
        ).fetchone()
        if row is None:
            return None
        course = self._row_to_course(row)
        course["site_url"] = None
        return course

    def get_course_by_repo(self, repo: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM courses WHERE repo = ? COLLATE NOCASE", (repo,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_course(row)

    def get_course_by_alias(self, alias: str) -> dict[str, Any] | None:
        """按别名 / readme.toml 中的 course_code 查询。

        历史课程仓的 `course_code` 字段并不总等于仓库名（例如 MATH1005K 仓里写的是
        MATH1005），因此课程身份一律以仓库为准，别名仅作为检索入口。
        """
        needle = alias.strip()
        if not needle:
            return None
        for row in self._conn.execute("SELECT * FROM courses"):
            if (row["course_code"] or "").lower() == needle.lower():
                return self._row_to_course(row)
            for item in _loads(row["aliases"], []):
                if item.lower() == needle.lower():
                    return self._row_to_course(row)
        return None

    def all_courses(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM courses ORDER BY code").fetchall()
        return [self._row_to_summary(row) for row in rows]

    def iter_courses_with_toml(self) -> list[Any]:
        """取出重算别名所需的字段（code / course_code / aliases / readme_toml）。"""
        return self._conn.execute(
            "SELECT code, course_code, aliases, readme_toml FROM courses ORDER BY code"
        ).fetchall()

    def update_course_aliases(self, code: str, aliases: list[str]) -> None:
        self._conn.execute(
            "UPDATE courses SET aliases = ? WHERE code = ?",
            (json.dumps(aliases, ensure_ascii=False), code),
        )

    def search_courses(
        self,
        keyword: str = "",
        teacher: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """轻量打分检索：课程代码 / 名称 / 别名 / 教师 / 描述。"""
        keyword = (keyword or "").strip()
        teacher = (teacher or "").strip()
        rows = self._conn.execute("SELECT * FROM courses").fetchall()

        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            summary = self._row_to_summary(row)
            aliases = summary["aliases"]
            names = summary["teachers"]
            score = 0.0

            if teacher:
                if not any(teacher == name or teacher in name for name in names):
                    continue
                score += 40

            if keyword:
                code = summary["code"].upper()
                kw = keyword.upper()
                if code == kw:
                    score += 100
                elif code.startswith(kw):
                    score += 60
                elif kw in code:
                    score += 45
                if (summary.get("course_code") or "").upper() == kw:
                    score += 70
                elif kw in (summary.get("course_code") or "").upper():
                    score += 40
                if keyword == summary["name"]:
                    score += 90
                elif keyword and keyword in summary["name"]:
                    score += 55
                if any(keyword == alias for alias in aliases):
                    score += 50
                elif any(keyword in alias for alias in aliases):
                    score += 30
                if any(keyword == name for name in names):
                    score += 45
                elif any(keyword in name for name in names):
                    score += 25
                if keyword in (row["description"] or ""):
                    score += 10
                if score <= 0:
                    continue
            elif not teacher:
                score = 1.0

            if summary["updated_at"]:
                score += min(5.0, 0.0)
            scored.append((score, summary))

        scored.sort(key=lambda item: (-item[0], item[1]["code"]))
        return [item[1] for item in scored[:limit]]

    def search_content_courses(self, keyword: str, limit: int = 20) -> list[dict[str, Any]]:
        """按课程正文（readme.toml / readme.md）检索。

        这是老 course-server 的 GitHub code search 兜底行为的本地等价物：
        老实现只有在缓存与昵称都没命中时，才去 GitHub 全库搜正文，
        因此正文命中只在直接检索无结果时启用。
        """
        needle = (keyword or "").strip()
        if len(needle) < 2:
            return []
        rows = self._conn.execute(
            "SELECT * FROM courses "
            "WHERE instr(readme_toml, ?) > 0 OR instr(readme_md, ?) > 0",
            (needle, needle),
        ).fetchall()
        results = [self._row_to_summary(row) for row in rows]
        results.sort(key=lambda item: item["code"])
        return results[:limit]

    def get_materials(self, course_code: str, path: str = "") -> list[dict[str, Any]]:
        if path:
            rows = self._conn.execute(
                "SELECT * FROM materials WHERE course_code = ? AND parent = ? ORDER BY type, name",
                (course_code, path),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM materials WHERE course_code = ? AND parent = '' ORDER BY type, name",
                (course_code,),
            ).fetchall()
        return [
            {
                "name": row["name"],
                "type": row["type"],
                "path": row["path"],
                "size": row["size"],
                "updated_at": row["updated_at"],
                "url": row["url"],
            }
            for row in rows
        ]

    def list_teachers(self, keyword: str = "", course: str = "") -> list[dict[str, Any]]:
        keyword = (keyword or "").strip()
        course = (course or "").strip()
        sql = "SELECT t.name AS name, t.course_code AS course_code, t.review_count AS rc FROM teachers t"
        params: list[str] = []
        where = []
        if keyword:
            where.append("t.name LIKE ?")
            params.append(f"%{keyword}%")
        if course:
            where.append("t.course_code = ? COLLATE NOCASE")
            params.append(course)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY t.name, t.course_code"

        grouped: dict[str, dict[str, Any]] = {}
        for row in self._conn.execute(sql, params):
            entry = grouped.setdefault(
                row["name"], {"name": row["name"], "courses": [], "review_count": 0}
            )
            entry["courses"].append(row["course_code"])
            entry["review_count"] += row["rc"] or 0
        return list(grouped.values())

    def get_grading(self, course_code: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT payload FROM grades WHERE course_code = ? COLLATE NOCASE", (course_code,)
        ).fetchone()
        if row:
            return _loads(row["payload"], {})
        course = self.get_course(course_code)
        if course and course.get("grading"):
            return course["grading"]
        return None

    def all_grading(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT g.course_code AS code, g.payload AS payload FROM grades g"
            " JOIN courses c ON c.code = g.course_code ORDER BY g.course_code"
        ).fetchall()
        return [{"code": row["code"], **_loads(row["payload"], {})} for row in rows]

    def get_plan(self, year: str, major: str) -> dict[str, Any] | None:
        rows = self._conn.execute(
            "SELECT payload FROM plans WHERE year = ? AND (major = ? OR major_code = ?)",
            (str(year), major, major),
        ).fetchall()
        if not rows:
            return None
        return _loads(rows[0]["payload"], None)

    def plan_index(self) -> dict[str, list[tuple[str, str, str]]]:
        """培养方案课程倒排索引：课程代码 → [(year, major_code, semester_slug)]。

        用于快速推导课程在站点上的页面地址，避免逐个方案线性扫描。
        """
        if self._plan_index is None:
            from .course_data import semester_slug

            index: dict[str, list[tuple[str, str, str]]] = {}
            for row in self._conn.execute(
                "SELECT year, major, major_code, payload FROM plans ORDER BY year DESC, major ASC"
            ):
                payload = _loads(row["payload"], {})
                major_ref = row["major_code"] or row["major"]
                for course in payload.get("courses", []):
                    code = str(course.get("course_code") or "").upper()
                    slug = semester_slug(course.get("recommended_semester"))
                    if not code or not slug:
                        continue
                    index.setdefault(code, []).append((row["year"], major_ref, slug))
            self._plan_index = index
        return self._plan_index

    def invalidate_plan_index(self) -> None:
        self._plan_index = None

    def list_plans(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT year, major, major_code, payload FROM plans ORDER BY year DESC, major"
        ).fetchall()
        return [
            {
                "year": row["year"],
                "major": row["major"],
                "major_code": row["major_code"],
                "course_count": len(_loads(row["payload"], {}).get("courses", [])),
            }
            for row in rows
        ]

    def prune_courses(self, valid_repos: set[str]) -> int:
        """删除已不在仓库清单中的课程（模板仓、已删仓等），返回清理条数。"""
        rows = self._conn.execute("SELECT code, repo FROM courses").fetchall()
        stale = [row["code"] for row in rows if row["repo"] not in valid_repos]
        for code in stale:
            self._conn.execute("DELETE FROM courses WHERE code = ?", (code,))
            self._conn.execute("DELETE FROM materials WHERE course_code = ?", (code,))
            self._conn.execute("DELETE FROM teachers WHERE course_code = ?", (code,))
        return len(stale)

    # ---------- sync bookkeeping ----------

    def get_repo_sync(self, repo: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM repo_sync WHERE repo = ?", (repo,)
        ).fetchone()

    def set_repo_sync(
        self,
        repo: str,
        *,
        etag_toml: str | None = None,
        etag_readme: str | None = None,
        etag_tree: str | None = None,
        status: str = "ok",
        error: str | None = None,
        synced_at: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO repo_sync(repo, etag_toml, etag_readme, etag_tree, status, error, synced_at)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(repo) DO UPDATE SET
                etag_toml=COALESCE(excluded.etag_toml, repo_sync.etag_toml),
                etag_readme=COALESCE(excluded.etag_readme, repo_sync.etag_readme),
                etag_tree=COALESCE(excluded.etag_tree, repo_sync.etag_tree),
                status=excluded.status, error=excluded.error,
                synced_at=COALESCE(excluded.synced_at, repo_sync.synced_at)
            """,
            (repo, etag_toml, etag_readme, etag_tree, status, error, synced_at),
        )

    def upsert_grade(self, course_code: str, payload: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO grades(course_code, payload) VALUES(?,?) "
            "ON CONFLICT(course_code) DO UPDATE SET payload=excluded.payload",
            (course_code, _dumps(payload)),
        )

    def upsert_plan(self, year: str, major: str, major_code: str, payload: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO plans(year, major, major_code, payload) VALUES(?,?,?,?) "
            "ON CONFLICT(year, major) DO UPDATE SET major_code=excluded.major_code, "
            "payload=excluded.payload",
            (year, major, major_code, _dumps(payload)),
        )
        self._plan_index = None
