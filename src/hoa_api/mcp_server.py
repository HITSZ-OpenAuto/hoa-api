"""MCP Server：把 HOA 数据以 MCP 工具与资源的形式暴露给任意 Agent。

传输：Streamable HTTP（无状态模式），端点默认 `/mcp`。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.mcpserver import MCPServer

from .config import Config
from .service import Service

INSTRUCTIONS = """\
HITSZ OpenAuto（HOA）官方 MCP 服务，提供哈工大（深圳）本科课程攻略、资料、教师与成绩构成数据。

典型用法：
1. `search_courses("自动控制")` 找到课程代码；
2. `get_course("AUTO3005")` 取课程完整信息（描述、章节、教师评价、成绩构成）；
3. `get_course_materials("AUTO3005")` 取资料文件树与下载地址；
4. `get_curriculum_plan("2022", "自动化")` 取培养方案。

课程内容的事实来源是各课程仓的 `readme.toml`，所有字段均为公开信息。
"""


def build_mcp(service: Service, config: Config) -> MCPServer:
    """构造 MCP Server 实例。"""
    mcp = MCPServer(
        name="hoa",
        instructions=INSTRUCTIONS,
        version="1.0.0",
    )

    @mcp.tool(
        description=(
            "检索 HITSZ（深圳）本科课程。支持关键词（课程代码/名称/别名/教师/描述）与教师名筛选，"
            "返回课程代码、名称、教师、别名、仓库地址与站点页地址。"
        )
    )
    def search_courses(q: str = "", teacher: str = "", limit: int = 20) -> dict[str, Any]:
        """按关键词或教师检索课程。

        Args:
            q: 关键词，例如「自动控制」「AUTO3005」「楼云江」。
            teacher: 教师姓名，精确或包含匹配。
            limit: 返回条数，默认 20，上限 100。
        """
        return {
            "items": service.find_courses(q=q, teacher=teacher, limit=limit),
            "query": {"q": q, "teacher": teacher, "limit": limit},
        }

    @mcp.tool(
        description=(
            "获取单门课程的完整结构化信息：课程简介、章节内容、教师与评价、成绩构成、学时学分。"
            "用 include 控制返回字段，materials 表示包含资料文件树。"
        )
    )
    def get_course(code: str, include: str = "summary,sections,lecturers,grading") -> dict[str, Any]:
        """获取课程详情。

        Args:
            code: 课程代码，例如「AUTO3005」。
            include: 逗号分隔的字段列表，可用 summary/sections/lecturers/grading/materials。
        """
        course = service.get_course(code)
        if not course:
            return {"error": {"code": "NOT_FOUND", "message": f"未找到课程 {code}"}}
        wanted = {part.strip() for part in include.split(",") if part.strip()}
        if "sections" not in wanted:
            course.pop("sections", None)
        if "lecturers" not in wanted:
            course.pop("lecturers", None)
        if "grading" not in wanted:
            course.pop("grading", None)
        if "materials" not in wanted:
            materials = service.get_materials(code)
            if materials:
                course["materials"] = materials
        return course

    @mcp.tool(description="获取课程原始 README。format=md 返回渲染后的 Markdown，format=toml 返回事实来源 readme.toml。")
    def get_course_readme(code: str, format: str = "md") -> str:
        """获取课程 README 原文。

        Args:
            code: 课程代码。
            format: md（默认）或 toml。
        """
        result = service.get_readme(code, format)
        if result is None:
            return json.dumps({"error": {"code": "NOT_FOUND", "message": f"未找到课程 {code}"}}, ensure_ascii=False)
        return result[0]

    @mcp.tool(description="获取课程资料文件树（试卷、作业、实验、笔记、课件等），含文件大小与下载地址。")
    def get_course_materials(code: str, path: str = "", limit: int = 100) -> dict[str, Any]:
        """获取课程资料文件树。

        Args:
            code: 课程代码。
            path: 子目录，如 exams；留空返回顶层目录。
            limit: 返回条数上限。
        """
        result = service.get_materials(code, path, limit)
        if result is None:
            return {"error": {"code": "NOT_FOUND", "message": f"未找到课程 {code}"}}
        return result

    @mcp.tool(description="查询教师及其所授课程，姓名支持模糊匹配。")
    def list_teachers(q: str = "", course: str = "") -> dict[str, Any]:
        """查询教师。

        Args:
            q: 教师姓名片段。
            course: 限定课程代码。
        """
        items = service.list_teachers(q=q, course=course)
        return {"items": items, "total": len(items)}

    @mcp.tool(description="获取课程成绩构成（平时/实验/期末占比等），数据来自 hoa-major-data。")
    def get_grading(code: str) -> dict[str, Any]:
        """获取成绩构成。

        Args:
            code: 课程代码。
        """
        payload = service.get_grading(code)
        if not payload:
            return {"error": {"code": "NOT_FOUND", "message": f"未找到 {code} 的成绩构成"}}
        return payload

    @mcp.tool(description="获取指定入学年份与专业的培养方案课程列表。")
    def get_curriculum_plan(year: str, major: str) -> dict[str, Any]:
        """获取培养方案。

        Args:
            year: 入学年份，如 2022。
            major: 专业名称或专业代码，如 自动化。
        """
        plan = service.get_plan(year, major)
        if not plan:
            return {"error": {"code": "NOT_FOUND", "message": f"未找到 {year} 年 {major} 的培养方案"}}
        return plan

    @mcp.tool(description="跨课程、教师检索 HOA 内容，返回带类型的命中列表。")
    def search_site(q: str, limit: int = 20) -> dict[str, Any]:
        """全站检索。

        Args:
            q: 关键词。
            limit: 返回条数。
        """
        items = service.search(q, limit)
        return {"items": items, "total": len(items)}

    # ---------------- 资源 ----------------

    @mcp.resource("hoa://course/{code}", description="课程结构化数据（JSON）")
    def course_resource(code: str) -> str:
        """课程 JSON。"""
        course = service.get_course(code)
        if not course:
            return json.dumps({"error": "NOT_FOUND"}, ensure_ascii=False)
        return json.dumps(course, ensure_ascii=False, indent=2)

    @mcp.resource("hoa://course/{code}/readme", description="课程 README（Markdown）")
    def course_readme_resource(code: str) -> str:
        """课程 README。"""
        result = service.get_readme(code, "md")
        return result[0] if result else ""

    @mcp.resource("hoa://teacher/{name}", description="教师信息与所授课程（JSON）")
    def teacher_resource(name: str) -> str:
        """教师 JSON。"""
        items = service.list_teachers(q=name)
        return json.dumps({"items": items}, ensure_ascii=False, indent=2)

    @mcp.resource("hoa://plan/{year}/{major}", description="培养方案（JSON）")
    def plan_resource(year: str, major: str) -> str:
        """培养方案 JSON。"""
        plan = service.get_plan(year, major)
        if not plan:
            return json.dumps({"error": "NOT_FOUND"}, ensure_ascii=False)
        return json.dumps(plan, ensure_ascii=False, indent=2)

    return mcp


def mount_mcp(app: Any, service: Service, config: Config) -> MCPServer:
    """把 MCP Streamable HTTP 端点挂到 FastAPI 应用上。

    注意：Starlette 的 ``Mount`` 不会把 lifespan 事件转发给子应用，
    而 MCP 的会话管理器正是在子应用的 lifespan 中启动的，
    因此这里显式接管 FastAPI 的 lifespan，串起 MCP 应用的启动与关闭。
    """
    mcp = build_mcp(service, config)
    mcp_app = mcp.streamable_http_app(
        streamable_http_path=config.mcp_path or "/mcp",
        json_response=True,
        stateless_http=True,
    )

    @asynccontextmanager
    async def lifespan(_: Any) -> AsyncIterator[None]:
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    app.router.lifespan_context = lifespan
    # 挂在根路径下：FastMCP 内部处理 `/mcp`，且不会与已注册的 REST 路由冲突
    app.mount("/", mcp_app)
    return mcp
