"""FastAPI 应用：官方 REST API + 兼容层。

- `/api/v1/*`  —— 官方 v1 契约（GET、公开、OpenAPI 描述）
- `/v1/*`      —— 与 HIT-A `course-server` 兼容的 POST 接口，便于平滑迁移
- `/mcp`       —— MCP Streamable HTTP 端点（见 mcp_server.py）
"""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import APIRouter, FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .config import Config, get_config
from .db import Store
from .service import Service

API_TITLE = "HITSZ OpenAuto (HOA) Public API"
API_VERSION = "1.0.0"


# --------------------------------------------------------------------------
# 限流
# --------------------------------------------------------------------------


class RateLimiter:
    """按 IP 的滑动窗口限流。"""

    def __init__(self, limit_per_min: int) -> None:
        self.limit = limit_per_min
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> tuple[bool, int]:
        now = time.time()
        window = self._hits[key]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self.limit:
            retry_after = int(60 - (now - window[0])) + 1
            return False, max(1, retry_after)
        window.append(now)
        self._evict(now)
        return True, 0

    def _evict(self, now: float) -> None:
        """清理长期不活跃的 IP，避免字典无限增长。"""
        if len(self._hits) < 1024:
            return
        stale = [key for key, window in self._hits.items() if not window or now - window[-1] > 600]
        for key in stale:
            self._hits.pop(key, None)


# --------------------------------------------------------------------------
# 兼容层请求体
# --------------------------------------------------------------------------


class CompatTarget(BaseModel):
    campus: str = "shenzhen"
    course_code: str
    course_name: str | None = None


class CompatCourseRead(BaseModel):
    target: CompatTarget
    include_toml: bool = False


class CompatCoursesSearch(BaseModel):
    keyword: str = ""
    campus: str = "shenzhen"
    limit: int = Field(default=10, ge=1, le=100)


# --------------------------------------------------------------------------
# 应用工厂
# --------------------------------------------------------------------------


def create_app(config: Config | None = None, store: Store | None = None) -> FastAPI:
    config = config or get_config()
    store = store or Store(config.db_path)
    service = Service(store, config)
    limiter = RateLimiter(config.rate_limit_per_min)

    app = FastAPI(
        title=API_TITLE,
        version=API_VERSION,
        description=(
            "哈工大（深圳）自动化本科开源计划官方接口。数据来自 "
            "[HITSZ-OpenAuto](https://github.com/HITSZ-OpenAuto) 组织的公开课程仓。"
        ),
        docs_url=f"{config.api_base_path}/docs",
        redoc_url=f"{config.api_base_path}/redoc",
        openapi_url=f"{config.api_base_path}/openapi.json",
    )
    app.state.store = store
    app.state.service = service
    app.state.config = config

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["ETag", "X-HOA-API-Version", "X-HOA-Data-Generated-At", "Retry-After"],
    )

    @app.middleware("http")
    async def rate_limit_and_etag(request: Request, call_next: Any) -> Response:
        client = request.client.host if request.client else "unknown"
        allowed, retry_after = limiter.allow(client)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "请求过于频繁，请稍后再试",
                    }
                },
                headers={"Retry-After": str(retry_after)},
            )

        response = await call_next(request)

        # MCP 端点不走 ETag 处理：其响应可能是 SSE 流，缓冲会破坏流式语义
        is_mcp = request.url.path.rstrip("/") == config.mcp_path.rstrip("/")

        if request.method == "GET" and response.status_code == 200 and not is_mcp:
            body = b""
            async for chunk in response.body_iterator:
                body += chunk
            etag = '"' + hashlib.sha256(body).hexdigest()[:24] + '"'
            headers = dict(response.headers)
            headers.pop("content-length", None)
            headers["etag"] = etag
            headers.setdefault("cache-control", "public, max-age=300, stale-while-revalidate=86400")
            headers["x-hoa-api-version"] = "v1"
            generated_at = store.get_meta("last_sync_at")
            if generated_at:
                headers["x-hoa-data-generated-at"] = generated_at

            if request.headers.get("if-none-match") == etag:
                return Response(status_code=304, headers=headers)
            response = Response(
                content=body, status_code=response.status_code, headers=headers, media_type=response.media_type
            )
        return response

    api = APIRouter(prefix=config.api_base_path)

    # ---------------- 课程 ----------------

    @api.get("/courses", tags=["courses"], summary="检索课程列表")
    def list_courses(
        q: str = Query("", description="关键词：课程代码 / 名称 / 别名 / 教师 / 描述"),
        teacher: str = Query("", description="教师姓名"),
        major: str = Query("", description="专业"),
        year: str = Query("", description="入学年份"),
        limit: int = Query(20, ge=1, le=100),
    ) -> dict[str, Any]:
        items = service.find_courses(q=q, teacher=teacher, limit=limit)
        return {"items": items, "total": len(items)}

    @api.get("/courses/{code}", tags=["courses"], summary="课程详情")
    def get_course(code: str, include: str = Query("sections,lecturers,grading")) -> Any:
        course = service.get_course(code)
        if not course:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "NOT_FOUND", "message": f"未找到课程 {code}"}},
            )
        wanted = {part.strip() for part in include.split(",") if part.strip()}
        if "sections" not in wanted:
            course.pop("sections", None)
        if "lecturers" not in wanted:
            course.pop("lecturers", None)
        if "grading" not in wanted:
            course.pop("grading", None)
        if "materials" in wanted:
            materials = service.get_materials(code)
            if materials:
                course["materials"] = materials
        return course

    @api.get("/courses/{code}/readme", tags=["courses"], summary="课程 README")
    def get_course_readme(code: str, format: str = Query("md", pattern="^(md|toml)$")) -> Response:
        result = service.get_readme(code, format)
        if result is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "NOT_FOUND", "message": f"未找到课程 {code}"}},
            )
        text, media_type = result
        return PlainTextResponse(text, media_type=media_type)

    @api.get("/courses/{code}/materials", tags=["courses"], summary="课程资料文件树")
    def get_course_materials(
        code: str,
        path: str = Query("", description="子目录路径"),
        limit: int = Query(200, ge=1, le=1000),
    ) -> Any:
        result = service.get_materials(code, path, limit)
        if result is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "NOT_FOUND", "message": f"未找到课程 {code}"}},
            )
        return result

    # ---------------- 教师 ----------------

    @api.get("/teachers", tags=["teachers"], summary="教师索引")
    def list_teachers(
        q: str = Query("", description="教师姓名"),
        course: str = Query("", description="课程代码"),
        limit: int = Query(50, ge=1, le=200),
    ) -> dict[str, Any]:
        items = service.list_teachers(q=q, course=course)[:limit]
        return {"items": items, "total": len(items)}

    # ---------------- 成绩 ----------------

    @api.get("/grades", tags=["grading"], summary="全部课程成绩构成")
    def list_grades(limit: int = Query(200, ge=1, le=500)) -> dict[str, Any]:
        items = service.all_grading()[:limit]
        return {"items": items, "total": len(items)}

    @api.get("/grades/{code}", tags=["grading"], summary="课程成绩构成")
    def get_grades(code: str) -> Any:
        payload = service.get_grading(code)
        if not payload:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "NOT_FOUND", "message": f"未找到 {code} 的成绩构成"}},
            )
        return payload

    # ---------------- 培养方案 ----------------

    @api.get("/plans", tags=["plans"], summary="培养方案列表")
    def list_plans() -> dict[str, Any]:
        items = service.list_plans()
        return {"items": items, "total": len(items)}

    @api.get("/plans/{year}/{major}", tags=["plans"], summary="培养方案详情")
    def get_plan(year: str, major: str) -> Any:
        plan = service.get_plan(year, major)
        if not plan:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "NOT_FOUND", "message": f"未找到 {year} 年 {major} 的培养方案"}},
            )
        return plan

    # ---------------- 检索 ----------------

    @api.get("/search", tags=["search"], summary="全站检索")
    def search(q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
        items = service.search(q, limit)
        return {"items": items, "total": len(items)}

    # ---------------- 元信息 ----------------

    @api.get("/meta", tags=["meta"], summary="服务元信息")
    def get_meta() -> dict[str, Any]:
        return service.meta()

    app.include_router(api)

    # ---------------- 兼容层（course-server） ----------------

    compat = APIRouter(prefix="/v1")

    @compat.post("/courses:search", summary="兼容 course-server：课程检索")
    def compat_courses_search(payload: CompatCoursesSearch) -> dict[str, Any]:
        items = service.find_courses(q=payload.keyword, limit=payload.limit)
        results = [
            {
                "code": item["code"],
                "name": item["name"],
                "org": config.org,
                "repo": item["repo"],
                "teachers": item.get("teachers", []),
                "aliases": item.get("aliases", []),
            }
            for item in items
        ]
        return {"ok": True, "data": {"results": results}}

    @compat.post("/course:read", summary="兼容 course-server：读取课程 README")
    def compat_course_read(payload: CompatCourseRead) -> dict[str, Any]:
        code = payload.target.course_code
        course = service.get_course(code)
        if not course:
            return {
                "ok": False,
                "error": {
                    "code": "COURSE_NOT_FOUND",
                    "message": f"未找到课程 {code}",
                    "details": {},
                },
            }
        result: dict[str, Any] = {"readme_md": course.get("readme_md", "")}
        if payload.include_toml:
            result["readme_toml"] = course.get("readme_toml", "")
        return {
            "ok": True,
            "data": {
                "base": {
                    "org": config.org,
                    "cache_org": config.org,
                    "repo": course["repo"],
                    "ref": "main",
                    "toml_path": "readme.toml",
                    "repo_type": course.get("repo_type", "normal"),
                },
                "result": result,
            },
        }

    app.include_router(compat)

    # ---------------- MCP ----------------

    from .mcp_server import mount_mcp

    mount_mcp(app, service, config)

    return app
