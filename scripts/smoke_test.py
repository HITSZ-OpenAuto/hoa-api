#!/usr/bin/env python3
"""端到端冒烟测试：REST 全部端点 + MCP 全部工具与资源 + 兼容层。

对任意一个运行中的 hoa-api 实例做黑盒验证，覆盖正常路径、边界情况与错误路径。
单元测试覆盖的是函数级行为，这个脚本覆盖的是「真的用 HTTP 打一遍」。

用法::

    # 造一份种子库并起服务
    python scripts/seed_db.py --out /tmp/hoa-seed.db
    HOA_DB_PATH=/tmp/hoa-seed.db HOA_PORT=8099 hoa-api serve &
    python scripts/smoke_test.py --base-url http://127.0.0.1:8099

    # 打到公网实例（此时用 --expect-data 断言数据非空）
    python scripts/smoke_test.py --base-url https://api.hoa.moe --expect-data

退出码：0 全部通过，1 存在失败。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    if condition:
        PASSED.append(name)
        print(f"  ✓ {name}")
    else:
        FAILED.append((name, detail))
        print(f"  ✗ {name}{('  → ' + detail) if detail else ''}")
    return condition


def _ci(headers: dict) -> dict:
    """响应头查找必须大小写不敏感。

    直连 uvicorn 时头名是小写，经反向代理后会被规范化成 Title-Case，
    直接用 ``headers.get("etag")`` 会在生产环境莫名其妙地取不到。
    """
    return {str(key).lower(): value for key, value in headers.items()}


def request(
    method: str,
    url: str,
    payload: dict | None = None,
    headers: dict | None = None,
) -> tuple[int, bytes, dict]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    all_headers = {"Content-Type": "application/json"} if data else {}
    all_headers.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=all_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc).encode(), {}


def jget(base: str, route: str, **params) -> tuple[int, object, dict]:
    url = base.rstrip("/") + route
    if params:
        url += "?" + urllib.parse.urlencode(params)
    status, body, headers = request("GET", url)
    try:
        return status, json.loads(body), headers
    except Exception:  # noqa: BLE001
        return status, body, headers


def jpost(base: str, route: str, payload: dict) -> tuple[int, object, dict]:
    status, body, headers = request("POST", base.rstrip("/") + route, payload)
    try:
        return status, json.loads(body), headers
    except Exception:  # noqa: BLE001
        return status, body, headers


def mcp(base: str, method: str, params: dict | None = None, req_id: int = 1) -> tuple[int, object]:
    status, body, _ = request(
        "POST",
        base.rstrip("/") + "/mcp",
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        },
        headers={"Accept": "application/json, text/event-stream"},
    )
    try:
        return status, json.loads(body)
    except Exception:  # noqa: BLE001
        return status, body


def mcp_result(body: object) -> dict:
    if isinstance(body, dict):
        return body.get("result") or {}
    return {}


def tool_text(result: dict) -> str:
    """取工具/资源的文本内容。

    工具调用用 ``content``，资源读取用 ``contents``，两者都是数组。
    """
    for key in ("content", "contents"):
        items = result.get(key) or []
        if not items:
            continue
        first = items[0]
        if isinstance(first, dict):
            return first.get("text", "")
        return str(first)
    return ""


def check_rest(base: str, expect_data: bool) -> None:
    print("\n== REST: 元信息与课程 ==")
    status, meta, headers = jget(base, "/api/v1/meta")
    check("GET /api/v1/meta → 200", status == 200, f"实际 {status}")
    if isinstance(meta, dict):
        check("meta.api_version == v1", meta.get("api_version") == "v1", str(meta.get("api_version")))
        check("meta 含 course_count", isinstance(meta.get("course_count"), int))
        check("meta 含 mcp_endpoint", bool(meta.get("mcp_endpoint")))
    check("meta 带 x-hoa-api-version 头", _ci(headers).get("x-hoa-api-version") == "v1")

    status, body, _ = jget(base, "/api/v1/courses", limit=5)
    check("GET /api/v1/courses → 200", status == 200, f"实际 {status}")
    if isinstance(body, dict):
        check("courses 返回 items 数组", isinstance(body.get("items"), list))
        check("courses 返回 total", isinstance(body.get("total"), int))
        if expect_data:
            check("courses 有数据", body.get("total", 0) > 0, f"total={body.get('total')}")

    status, body, _ = jget(base, "/api/v1/courses", q="机器人")
    check("GET /api/v1/courses?q=机器人 → 200", status == 200)
    if isinstance(body, dict) and expect_data:
        names = [item.get("name") for item in body.get("items", [])]
        check(
            "q=机器人 能命中机器人相关课程",
            any("机器人" in (name or "") for name in names),
            str(names[:5]),
        )

    status, body, _ = jget(base, "/api/v1/courses", q="高数")
    check("GET /api/v1/courses?q=高数 → 200", status == 200)
    if isinstance(body, dict) and expect_data:
        names = [item.get("name") for item in body.get("items", [])]
        check(
            "昵称「高数」能命中微积分",
            any("微积分" in (name or "") for name in names),
            str(names[:5]),
        )

    status, body, _ = jget(base, "/api/v1/courses", q="EE3004")
    check("GET /api/v1/courses?q=EE3004 → 200", status == 200)
    if isinstance(body, dict) and expect_data:
        names = [item.get("name") for item in body.get("items", [])]
        check(
            "子课程代码 EE3004 命中其母课程仓",
            any("电气专业选修课" in (name or "") for name in names),
            str(names[:5]),
        )

    status, _, _ = jget(base, "/api/v1/courses", limit=0)
    check("limit=0 → 422", status == 422, f"实际 {status}")
    status, _, _ = jget(base, "/api/v1/courses", limit=1000)
    check("limit=1000 → 422", status == 422, f"实际 {status}")

    print("\n== REST: 课程详情 / README / 资料 ==")
    status, body, _ = jget(base, "/api/v1/courses/AUTO3005")
    check("GET /api/v1/courses/AUTO3005 → 200", status == 200, f"实际 {status}")
    if isinstance(body, dict):
        check("详情含 code/name", body.get("code") == "AUTO3005" and bool(body.get("name")))
        check("详情含 teachers", isinstance(body.get("teachers"), list))
    status, _, _ = jget(base, "/api/v1/courses/DOES-NOT-EXIST")
    check("GET /api/v1/courses/<不存在> → 404", status == 404, f"实际 {status}")

    status, body, headers = jget(base, "/api/v1/courses/AUTO3005/readme")
    check("GET /api/v1/courses/AUTO3005/readme → 200", status == 200, f"实际 {status}")
    check(
        "readme 是 Markdown",
        "markdown" in _ci(headers).get("content-type", "").lower(),
        _ci(headers).get("content-type", ""),
    )
    status, body, headers = jget(base, "/api/v1/courses/AUTO3005/readme", format="toml")
    check("readme?format=toml → 200", status == 200, f"实际 {status}")
    status, _, _ = jget(base, "/api/v1/courses/AUTO3005/readme", format="bogus")
    check("readme?format=bogus → 422", status == 422, f"实际 {status}")

    status, body, _ = jget(base, "/api/v1/courses/AUTO3005/materials")
    check("GET /api/v1/courses/AUTO3005/materials → 200", status == 200, f"实际 {status}")
    if isinstance(body, dict):
        check("materials 含 nodes/total", "nodes" in body and "total" in body)
    status, body, _ = jget(base, "/api/v1/courses/AUTO3005/materials", path="exams")
    check("materials?path=exams → 200", status == 200, f"实际 {status}")
    status, _, _ = jget(base, "/api/v1/courses/DOES-NOT-EXIST/materials")
    check("materials <不存在> → 404", status == 404, f"实际 {status}")

    print("\n== REST: 教师 / 成绩 / 培养方案 ==")
    status, body, _ = jget(base, "/api/v1/teachers", limit=10)
    check("GET /api/v1/teachers → 200", status == 200, f"实际 {status}")
    if isinstance(body, dict):
        check("teachers 返回 items", isinstance(body.get("items"), list))
    status, body, _ = jget(base, "/api/v1/teachers", q="楼云江")
    if isinstance(body, dict) and expect_data:
        names = [item.get("name") for item in body.get("items", [])]
        check("teachers?q=楼云江 命中", "楼云江" in names, str(names[:5]))

    status, body, _ = jget(base, "/api/v1/grades", limit=10)
    check("GET /api/v1/grades → 200", status == 200, f"实际 {status}")
    if isinstance(body, dict):
        check("grades 返回 items", isinstance(body.get("items"), list))
    status, body, _ = jget(base, "/api/v1/grades/AUTO3005")
    check("GET /api/v1/grades/AUTO3005 → 200", status == 200, f"实际 {status}")
    status, _, _ = jget(base, "/api/v1/grades/DOES-NOT-EXIST")
    check("grades <不存在> → 404", status == 404, f"实际 {status}")

    status, body, _ = jget(base, "/api/v1/plans")
    check("GET /api/v1/plans → 200", status == 200, f"实际 {status}")
    if isinstance(body, dict) and expect_data:
        check("plans 有数据", body.get("total", 0) > 0)
    status, body, _ = jget(base, "/api/v1/plans/2022/" + urllib.parse.quote("自动化"))
    check("GET /api/v1/plans/2022/自动化 → 200", status == 200, f"实际 {status}")
    if isinstance(body, dict) and expect_data:
        check("培养方案含课程列表", len(body.get("courses") or []) > 0)
    status, _, _ = jget(base, "/api/v1/plans/1999/none")
    check("plans <不存在> → 404", status == 404, f"实际 {status}")

    print("\n== REST: 全站检索 ==")
    status, body, _ = jget(base, "/api/v1/search", q="机器人", limit=5)
    check("GET /api/v1/search?q=机器人 → 200", status == 200, f"实际 {status}")
    if isinstance(body, dict):
        check("search 返回 items", isinstance(body.get("items"), list))
    status, _, _ = jget(base, "/api/v1/search", q="")
    check("search 空关键词 → 422（q 必填且 min_length=1）", status == 422, f"实际 {status}")

    print("\n== REST: 缓存与异常 ==")
    status, _, headers = jget(base, "/api/v1/courses", limit=3)
    etag = _ci(headers).get("etag")
    check("GET 带 ETag 头", bool(etag), str(headers))
    if etag:
        status, _, _ = request(
            "GET", base.rstrip("/") + "/api/v1/courses?limit=3", headers={"If-None-Match": etag}
        )
        check("If-None-Match 命中 → 304", status == 304, f"实际 {status}")

    status, _, _ = jget(base, "/api/v1/nope")
    check("未知路径 → 404", status == 404, f"实际 {status}")
    status, _, _ = jget(base, "/api/v1/courses", q="' OR 1=1 --")
    check("注入样式的关键词不报错", status == 200, f"实际 {status}")
    status, _, _ = jget(base, "/api/v1/courses", q="<script>alert(1)</script>")
    check("HTML 样式的关键词不报错", status == 200, f"实际 {status}")
    status, _, _ = jget(base, "/api/v1/courses", q="自动控制" * 20)
    check("超长关键词不报错", status == 200, f"实际 {status}")


def check_mcp(base: str, expect_data: bool) -> None:
    print("\n== MCP: 握手与工具清单 ==")
    status, body = mcp(
        base,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "smoke-test", "version": "1.0"},
        },
    )
    check("initialize → 200", status == 200, f"实际 {status}")
    result = mcp_result(body)
    check("initialize 返回 protocolVersion", bool(result.get("protocolVersion")))

    status, body = mcp(base, "tools/list")
    tools = mcp_result(body).get("tools") or []
    names = [tool.get("name") for tool in tools]
    expected = [
        "search_courses",
        "get_course",
        "get_course_readme",
        "get_course_materials",
        "list_teachers",
        "get_grading",
        "get_curriculum_plan",
        "search_site",
    ]
    check("tools/list 返回 8 个工具", len(tools) == 8, f"实际 {len(tools)}: {names}")
    missing = [name for name in expected if name not in names]
    check("工具名齐全", not missing, f"缺少 {missing}")
    check("每个工具都有描述", all(tool.get("description") for tool in tools))

    print("\n== MCP: 工具调用 ==")
    status, body = mcp(base, "tools/call", {"name": "search_courses", "arguments": {"q": "机器人", "limit": 5}}, 2)
    check("tools/call search_courses → 200", status == 200, f"实际 {status}")
    payload = json.loads(tool_text(mcp_result(body)) or "{}")
    if expect_data:
        check("search_courses 返回课程", len(payload.get("items") or []) > 0)

    status, body = mcp(base, "tools/call", {"name": "get_course", "arguments": {"code": "AUTO3005"}}, 3)
    check("tools/call get_course → 200", status == 200, f"实际 {status}")
    payload = json.loads(tool_text(mcp_result(body)) or "{}")
    check("get_course 返回 AUTO3005", payload.get("code") == "AUTO3005", str(payload.get("code")))

    status, body = mcp(base, "tools/call", {"name": "get_course", "arguments": {"code": "NOPE-NOPE"}}, 4)
    payload = json.loads(tool_text(mcp_result(body)) or "{}")
    check("get_course 未知课程返回 NOT_FOUND", payload.get("error", {}).get("code") == "NOT_FOUND")

    status, body = mcp(base, "tools/call", {"name": "get_course_readme", "arguments": {"code": "AUTO3005"}}, 5)
    check("tools/call get_course_readme → 200", status == 200, f"实际 {status}")
    check("readme 内容非空", len(tool_text(mcp_result(body))) > 0)

    status, body = mcp(base, "tools/call", {"name": "get_course_materials", "arguments": {"code": "AUTO3005"}}, 6)
    check("tools/call get_course_materials → 200", status == 200, f"实际 {status}")

    status, body = mcp(base, "tools/call", {"name": "list_teachers", "arguments": {"q": "楼云江"}}, 7)
    check("tools/call list_teachers → 200", status == 200, f"实际 {status}")

    status, body = mcp(base, "tools/call", {"name": "get_grading", "arguments": {"code": "AUTO3005"}}, 8)
    check("tools/call get_grading → 200", status == 200, f"实际 {status}")

    status, body = mcp(base, "tools/call", {"name": "get_curriculum_plan", "arguments": {"year": "2022", "major": "自动化"}}, 9)
    check("tools/call get_curriculum_plan → 200", status == 200, f"实际 {status}")

    status, body = mcp(base, "tools/call", {"name": "search_site", "arguments": {"q": "机器人"}}, 10)
    check("tools/call search_site → 200", status == 200, f"实际 {status}")

    status, body = mcp(base, "tools/call", {"name": "no_such_tool", "arguments": {}}, 11)
    # MCP SDK 对未知工具返回 isError 的 result（而不是 JSON-RPC error 对象）
    unknown_tool_failed = isinstance(body, dict) and (
        "error" in body or mcp_result(body).get("isError") is True
    )
    check("未知工具返回错误", unknown_tool_failed, str(body)[:160])

    print("\n== MCP: 资源 ==")
    status, body = mcp(base, "resources/templates/list")
    templates = mcp_result(body).get("resourceTemplates") or []
    uris = [t.get("uriTemplate") for t in templates]
    check("resources/templates/list → 4 个模板", len(templates) == 4, f"实际 {len(templates)}: {uris}")
    for expected_uri in (
        "hoa://course/{code}",
        "hoa://course/{code}/readme",
        "hoa://teacher/{name}",
        "hoa://plan/{year}/{major}",
    ):
        check(f"资源模板存在 {expected_uri}", expected_uri in uris)

    status, body = mcp(base, "resources/list")
    check("resources/list → 200", status == 200, f"实际 {status}")

    status, body = mcp(base, "resources/read", {"uri": "hoa://course/AUTO3005"}, 12)
    check("resources/read hoa://course/AUTO3005 → 200", status == 200, f"实际 {status}")
    check("资源内容非空", len(tool_text(mcp_result(body))) > 0)

    status, body = mcp(base, "resources/read", {"uri": "hoa://course/AUTO3005/readme"}, 13)
    check("resources/read hoa://course/AUTO3005/readme → 200", status == 200, f"实际 {status}")

    status, body = mcp(base, "resources/read", {"uri": "hoa://teacher/楼云江"}, 14)
    check("resources/read hoa://teacher/楼云江 → 200", status == 200, f"实际 {status}")

    status, body = mcp(
        base,
        "resources/read",
        {"uri": "hoa://plan/2022/" + urllib.parse.quote("自动化")},
        15,
    )
    check("resources/read hoa://plan/2022/自动化 → 200", status == 200, f"实际 {status}")


def check_compat(base: str, expect_data: bool) -> None:
    print("\n== 兼容层 (/v1) ==")
    status, body, _ = jpost(base, "/v1/courses:search", {"keyword": "机器人", "limit": 5})
    check("POST /v1/courses:search → 200", status == 200, f"实际 {status}")
    if isinstance(body, dict):
        check("兼容层信封 {ok, data.results}", body.get("ok") is True and "results" in (body.get("data") or {}))
        results = (body.get("data") or {}).get("results") or []
        if expect_data:
            check("兼容层检索有结果", len(results) > 0)
            if results:
                item = results[0]
                check("兼容层结果含 code/name/org/repo", all(k in item for k in ("code", "name", "org", "repo")))
                check("兼容层结果 teachers 是数组", isinstance(item.get("teachers"), list))

    status, body, _ = jpost(base, "/v1/courses:search", {"keyword": "机器人", "campus": "harbin", "limit": 5})
    check("兼容层接受 campus 参数", status == 200, f"实际 {status}")

    status, body, _ = jpost(base, "/v1/courses:search", {"keyword": "机器人", "limit": 1})
    if isinstance(body, dict) and expect_data:
        results = (body.get("data") or {}).get("results") or []
        check("兼容层忽略 limit（老服务语义）", len(results) > 1, f"实际 {len(results)} 条")

    status, body, _ = jpost(
        base,
        "/v1/course:read",
        {"target": {"campus": "shenzhen", "course_code": "AUTO3005"}, "include_toml": True},
    )
    check("POST /v1/course:read → 200", status == 200, f"实际 {status}")
    if isinstance(body, dict) and body.get("ok"):
        data = body.get("data") or {}
        check("兼容层 read 含 base/result", "base" in data and "result" in data)
        check("base 含 org/repo/repo_type", all(k in (data.get("base") or {}) for k in ("org", "repo", "repo_type")))
        check("include_toml 时含 readme_toml", "readme_toml" in (data.get("result") or {}))

    status, body, _ = jpost(
        base,
        "/v1/course:read",
        {"target": {"campus": "shenzhen", "course_code": "NOPE-NOPE"}},
    )
    check("兼容层 read 未知课程 → ok=false", isinstance(body, dict) and body.get("ok") is False, str(body)[:120])


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="hoa-api 端到端冒烟测试")
    parser.add_argument("--base-url", default="http://127.0.0.1:8099")
    parser.add_argument(
        "--expect-data",
        action="store_true",
        help="断言数据非空（打到真实实例时使用；种子库模式下应为真）",
    )
    args = parser.parse_args(argv)

    print(f"冒烟测试目标: {args.base_url}")
    check_rest(args.base_url, args.expect_data)
    check_mcp(args.base_url, args.expect_data)
    check_compat(args.base_url, args.expect_data)

    print(f"\n{'=' * 52}")
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    for name, detail in FAILED:
        print(f"  ✗ {name}  {detail}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
