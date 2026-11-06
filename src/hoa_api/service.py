"""业务服务层：REST 与 MCP 共用同一套查询逻辑。"""

from __future__ import annotations

import urllib.parse
from typing import Any

from .config import Config
from .db import Store

SEMESTER_MAP = {
    ("第一学年", "秋季"): "fresh-autumn",
    ("第一学年", "春季"): "fresh-spring",
    ("第二学年", "秋季"): "sophomore-autumn",
    ("第二学年", "春季"): "sophomore-spring",
    ("第三学年", "秋季"): "junior-autumn",
    ("第三学年", "春季"): "junior-spring",
    ("第四学年", "秋季"): "senior-autumn",
    ("第四学年", "春季"): "senior-spring",
}


class Service:
    """对外暴露的数据查询能力。"""

    def __init__(self, store: Store, config: Config) -> None:
        self.store = store
        self.config = config

    # ---------- 课程 ----------

    def find_courses(
        self,
        q: str = "",
        teacher: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        results = self.store.search_courses(keyword=q, teacher=teacher, limit=limit)
        for item in results:
            item["site_url"] = self.site_url(item["code"])
        return results

    def get_course(self, code: str) -> dict[str, Any] | None:
        """按任意标识取课程：仓库 ID、readme.toml 的 course_code 或别名。"""
        course = (
            self.store.get_course(code)
            or self.store.get_course_by_repo(code)
            or self.store.get_course_by_alias(code)
        )
        if not course:
            return None
        course["site_url"] = self.site_url(course["code"])
        course["grading"] = self.store.get_grading(course["code"]) or course.get("grading") or {}
        return course

    def identifiers(self, course: dict[str, Any]) -> set[str]:
        """课程在培养方案里可能用到的全部标识。"""
        values = {
            str(course.get("code") or ""),
            str(course.get("course_code") or ""),
            str(course.get("repo") or ""),
        }
        values.update(str(item) for item in course.get("aliases") or [])
        return {value.strip().upper() for value in values if value.strip()}

    def get_readme(self, code: str, fmt: str = "md") -> tuple[str, str] | None:
        course = self.get_course(code)
        if not course:
            return None
        if fmt == "toml":
            return course.get("readme_toml") or "", "application/toml"
        return course.get("readme_md") or "", "text/markdown; charset=utf-8"

    def get_materials(self, code: str, path: str = "", limit: int = 200) -> dict[str, Any] | None:
        course = self.get_course(code)
        if not course:
            return None
        nodes = self.store.get_materials(course["code"], path)
        return {
            "code": course["code"],
            "path": path,
            "nodes": nodes[:limit],
            "total": len(nodes),
        }

    # ---------- 教师 ----------

    def list_teachers(self, q: str = "", course: str = "") -> list[dict[str, Any]]:
        return self.store.list_teachers(keyword=q, course=course)

    # ---------- 成绩 ----------

    def get_grading(self, code: str) -> dict[str, Any] | None:
        payload = self.store.get_grading(code)
        if not payload:
            return None
        return {"code": code.upper(), **payload}

    def all_grading(self) -> list[dict[str, Any]]:
        return self.store.all_grading()

    # ---------- 培养方案 ----------

    def get_plan(self, year: str, major: str) -> dict[str, Any] | None:
        plan = self.store.get_plan(year, major)
        if not plan:
            return None
        for course in plan.get("courses", []):
            code = course.get("course_code")
            if code:
                course["repo"] = self._repo_for_code(code)
                course["site_url"] = self.site_url(code)
        return plan

    def list_plans(self) -> list[dict[str, Any]]:
        return self.store.list_plans()

    # ---------- 检索 ----------

    def search(self, q: str, limit: int = 20) -> list[dict[str, Any]]:
        """课程 + 教师 + 资料文件名的统一检索。"""
        hits: list[dict[str, Any]] = []
        keyword = (q or "").strip()
        if not keyword:
            return hits

        for course in self.find_courses(q=keyword, limit=limit):
            hits.append(
                {
                    "type": "course",
                    "title": f"{course['code']} {course['name']}".strip(),
                    "description": course.get("teachers") and "教师：" + "、".join(course["teachers"]) or "",
                    "url": course.get("site_url") or course.get("url"),
                    "code": course["code"],
                    "score": 50,
                }
            )

        for teacher in self.list_teachers(q=keyword)[: max(0, limit // 2)]:
            hits.append(
                {
                    "type": "teacher",
                    "title": teacher["name"],
                    "description": "教师，涉及课程：" + "、".join(teacher["courses"][:8]),
                    # 站点检索是弹窗，没有可分享的搜索页；这里指向 GitHub 组织内检索
                    "url": f"https://github.com/{self.config.org}?q={urllib.parse.quote(teacher['name'])}",
                    "score": 30,
                }
            )

        hits.sort(key=lambda item: -item["score"])
        return hits[:limit]

    # ---------- 元信息 ----------

    def meta(self) -> dict[str, Any]:
        return {
            "api_version": "v1",
            "generated_at": self.store.get_meta("last_sync_at"),
            "data_commit": self.store.get_meta("data_commit"),
            "course_count": self.store.count_courses(),
            "teacher_count": self.store.count_teachers(),
            "org": self.config.org,
            "mcp_endpoint": f"{self.config.site_origin.rstrip('/')}{self.config.mcp_path}",
            "base_url": self.config.public_base_url,
        }

    # ---------- 内部 ----------

    def _repo_for_code(self, code: str) -> str | None:
        """按任意标识反查课程所在仓库。"""
        course = (
            self.store.get_course(code)
            or self.store.get_course_by_repo(code)
            or self.store.get_course_by_alias(code)
        )
        return course["repo"] if course else None

    def site_url(self, code: str) -> str | None:
        """根据培养方案推导站点课程页地址。

        培养方案里的 course_code 可能与仓库 ID 不一致（历史遗留），
        因此用课程的全部标识做匹配。
        """
        course = self.store.get_course(code) or self.store.get_course_by_repo(code)
        if not course:
            return None
        wanted = self.identifiers(course)

        index = self.store.plan_index()
        for identifier in wanted:
            for year, major_ref, slug in index.get(identifier.upper(), []):
                return (
                    f"{self.config.site_origin.rstrip('/')}/docs/{year}/{major_ref}/{slug}/{identifier}"
                )
        return None
