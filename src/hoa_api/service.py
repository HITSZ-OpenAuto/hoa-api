"""业务服务层：REST 与 MCP 共用同一套查询逻辑。"""

from __future__ import annotations

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


def semester_slug(text: str | None) -> str | None:
    """把「第一学年秋季」映射成站点路径片段 `fresh-autumn`。"""
    if not text:
        return None
    for (year_part, term), slug in SEMESTER_MAP.items():
        if year_part in text and term in text:
            return slug
    return None


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
        course = self.store.get_course(code) or self.store.get_course_by_repo(code)
        if not course:
            return None
        course["site_url"] = self.site_url(course["code"])
        course["grading"] = self.store.get_grading(course["code"]) or course.get("grading") or {}
        return course

    def get_readme(self, code: str, fmt: str = "md") -> tuple[str, str] | None:
        course = self.get_course(code)
        if not course:
            return None
        if fmt == "toml":
            return course.get("readme_toml") or "", "application/toml"
        return course.get("readme_md") or "", "text/markdown; charset=utf-8"

    def get_materials(self, code: str, path: str = "", limit: int = 200) -> dict[str, Any] | None:
        course = self.store.get_course(code) or self.store.get_course_by_repo(code)
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
                    "url": f"{self.config.site_origin}/docs/search?q={teacher['name']}",
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
        course = self.store.get_course(code)
        if course:
            return course["repo"]
        course = self.store.get_course_by_repo(code)
        return course["repo"] if course else None

    def site_url(self, code: str) -> str | None:
        """根据培养方案推导站点课程页地址。"""
        plans = self.store.list_plans()
        for plan in plans:
            detail = self.store.get_plan(plan["year"], plan["major"])
            if not detail:
                continue
            for course in detail.get("courses", []):
                if (course.get("course_code") or "").upper() != code.upper():
                    continue
                slug = semester_slug(course.get("recommended_semester"))
                major_code = detail.get("major_code")
                if slug and major_code:
                    return (
                        f"{self.config.site_origin.rstrip('/')}/docs/"
                        f"{detail['year']}/{major_code}/{slug}/{code}"
                    )
        return None
