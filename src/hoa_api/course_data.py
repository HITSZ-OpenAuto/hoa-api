"""`readme.toml` 解析与规范化。

课程仓的 SSOT 是 `readme.toml`，字段定义见 HITSZ-OpenAuto/course-template。
解析需容忍历史遗留的 schema 差异，缺失字段一律降级为空值而非报错。
"""

from __future__ import annotations

from typing import Any

try:  # Python 3.11+
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - 兼容 3.10
    import tomli as _toml  # type: ignore[no-redef]


def loads_toml(text: str) -> dict[str, Any]:
    """解析 TOML 文本，失败时返回空字典。"""
    if not text.strip():
        return {}
    try:
        return _toml.loads(text)
    except Exception:
        return {}


def _authored_items(raw_items: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not isinstance(raw_items, list):
        return items
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, str):
            content = "" if content is None else str(content)
        author = item.get("author")
        author_norm = None
        if isinstance(author, dict):
            author_norm = {
                "name": author.get("name"),
                "link": author.get("link"),
                "date": author.get("date"),
            }
        elif isinstance(author, str):
            author_norm = {"name": author, "link": None, "date": None}
        items.append({"content": content, "author": author_norm})
    return items


def normalize_lecturers(raw: Any) -> dict[str, Any]:
    """把 `lecturers` 段规范化为 {intro, items, summary}。"""
    result: dict[str, Any] = {"intro": [], "items": [], "summary": []}
    if not isinstance(raw, dict):
        return result

    result["intro"] = _authored_items(raw.get("intro"))
    result["summary"] = _authored_items(raw.get("summary"))

    lecturers: list[dict[str, Any]] = []
    for item in raw.get("items") or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not name:
            continue
        lecturers.append(
            {
                "name": str(name),
                "reviews": _authored_items(item.get("reviews")),
            }
        )
    result["items"] = lecturers
    return result


def normalize_sections(raw: Any) -> list[dict[str, Any]]:
    """把 `sections` 段规范化为 [{title, items}]。"""
    sections: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return sections
    for section in raw:
        if not isinstance(section, dict):
            continue
        title = section.get("title") or "未命名章节"
        sections.append({"title": str(title), "items": _authored_items(section.get("items"))})
    return sections


def lecturer_names(lecturers: dict[str, Any]) -> list[str]:
    """按出现顺序去重后的教师名。"""
    seen: list[str] = []
    for lecturer in lecturers.get("items", []):
        name = (lecturer.get("name") or "").strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def teacher_review_counts(lecturers: dict[str, Any]) -> list[tuple[str, int]]:
    """教师 -> 评价条数。"""
    return [
        ((lecturer.get("name") or "").strip(), len(lecturer.get("reviews", [])))
        for lecturer in lecturers.get("items", [])
        if (lecturer.get("name") or "").strip()
    ]


def parse_course_toml(text: str) -> dict[str, Any]:
    """解析 `readme.toml`，返回规范化字段。"""
    data = loads_toml(text)
    lecturers = normalize_lecturers(data.get("lecturers"))
    return {
        "name": str(data.get("course_name") or "").strip(),
        "code": str(data.get("course_code") or "").strip(),
        "repo_type": str(data.get("repo_type") or "normal").strip(),
        "description": str(data.get("description") or "").strip(),
        "lecturers": lecturers,
        "sections": normalize_sections(data.get("sections")),
        "teachers": lecturer_names(lecturers),
    }


def parse_grading_payload(payload: Any) -> dict[str, Any]:
    """规范化 `grades_summary.json` 中的成绩构成。

    原始形如 ``{"default": [...], "2021_default": [...]}``，
    统一为 ``{"variants": {...}, "items": [...]}``，items 取 default 变体。
    """
    if not isinstance(payload, dict):
        return {"variants": {}, "items": []}
    variants: dict[str, list[dict[str, Any]]] = {}
    for key, value in payload.items():
        if isinstance(value, list):
            variants[str(key)] = [
                {
                    "name": str(item.get("name", "")),
                    "percent": item.get("percent"),
                }
                for item in value
                if isinstance(item, dict)
            ]
    default = variants.get("default") or []
    if not default and variants:
        default = next(iter(variants.values()))
    return {"variants": variants, "items": default}


def parse_plan_toml(text: str) -> dict[str, Any]:
    """解析培养方案 TOML。"""
    data = loads_toml(text)
    info = data.get("info") if isinstance(data.get("info"), dict) else {}
    courses = []
    for course in data.get("courses") or []:
        if not isinstance(course, dict):
            continue
        courses.append(
            {
                "course_code": course.get("course_code"),
                "course_name": course.get("course_name"),
                "credit": course.get("credit"),
                "assessment_method": course.get("assessment_method"),
                "course_nature": course.get("course_nature"),
                "recommended_semester": course.get("recommended_year_semester"),
                "hours": course.get("hours"),
            }
        )
    return {
        "year": str(info.get("year") or ""),
        "major": str(info.get("major_name") or ""),
        "major_code": str(info.get("major_code") or ""),
        "school_name": info.get("school_name"),
        "study_level": info.get("study_level") or ("undergrad" if "本" in str(info.get("major_name", "")) else None),
        "courses": courses,
    }
