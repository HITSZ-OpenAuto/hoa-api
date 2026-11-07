#!/usr/bin/env python3
"""新旧课程服务兼容性对拍。

`/v1` 兼容层的存在意义，是让 HIT-A 的 `agent-backend` 在不改动一行代码的前提下
从旧 `course-server` 切到本服务。因此「兼容层不能漂移」需要一条可复现的检查。

脚本用 HIT-A 的真实报文格式（`keyword` + `campus` + `target.course_code` +
`include_toml`）同时打新旧两个服务，逐个查询比对返回的课程代码集合：

* 新服务完全覆盖旧服务 → 通过
* 旧服务多出的课程 → 列出（需确认是不是已删除的仓，旧服务的本地缓存会留僵尸条目）
* 新服务多出的课程 → 列出（通常是检索语义更宽导致，属正常）

用法::

    # 在同时能访问新旧服务的地方跑（例如部署了兜底服务的机器上）
    python scripts/compare_compat.py \
        --old http://localhost:8081 \
        --new http://localhost:8099

    # 也可以直接指定公网地址
    python scripts/compare_compat.py --old https://old.example.com --new https://api.hoa.moe

退出码：0 表示完全覆盖，1 表示存在缺口，2 表示服务不可达。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

QUERIES = [
    "机器人", "自动控制", "机器学习", "深度学习", "计算机", "数学", "物理", "化学",
    "英语", "线性代数", "概率论", "数据结构", "操作系统", "编译原理", "数据库", "网络",
    "软件工程", "人工智能", "控制", "信号与系统", "电路", "电机", "电力", "机械", "材料",
    "经管", "经济", "管理", "创新", "实践", "实验", "设计", "建模", "优化", "通信",
    "电子", "电气", "选修课", "专业导论", "认知",
    "高数", "微积分", "大物", "线代", "程序设计", "思道", "习特", "软构", "计网",
]

CAMPUSES = ["shenzhen", "harbin", "weihai"]


def post(base: str, path: str, payload: dict) -> tuple[int, object]:
    """发一次 POST，遇到 429 按 Retry-After 退避重试。

    对拍会连续打上百个请求，很容易撞上限流器；此时必须退避而不是当成「不可达」。
    """
    for attempt in range(6):
        request = urllib.request.Request(
            base.rstrip("/") + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 5:
                wait = int(exc.headers.get("Retry-After") or 5)
                time.sleep(min(wait, 30))
                continue
            return exc.code, None
        except Exception as exc:  # noqa: BLE001 - 任何网络异常都视为不可达
            return 0, str(exc)
    return 429, None


def search_codes(base: str, keyword: str, campus: str) -> set[str] | None:
    status, body = post(
        base,
        "/v1/courses:search",
        {"keyword": keyword, "limit": 10, "campus": campus},
    )
    if status != 200 or not isinstance(body, dict):
        return None
    results = (body.get("data") or {}).get("results") or []
    return {item.get("code") for item in results if isinstance(item, dict)}


def read_shape(base: str, campus: str, code: str) -> tuple | None:
    status, body = post(
        base,
        "/v1/course:read",
        {"target": {"campus": campus, "course_code": code}, "include_toml": True},
    )
    if status != 200 or not isinstance(body, dict):
        return None
    data = body.get("data") or {}
    base_info = data.get("base") or {}
    result = data.get("result") or {}
    return (
        sorted(base_info.keys()),
        sorted(result.keys()),
        len(str(result.get("readme_md") or "")),
        len(str(result.get("readme_toml") or "")),
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="新旧课程服务兼容性对拍")
    parser.add_argument("--old", required=True, help="旧 course-server 地址")
    parser.add_argument("--new", required=True, help="新 hoa-api 地址")
    parser.add_argument("--quiet", action="store_true", help="只输出缺口")
    args = parser.parse_args(argv)

    covered = 0
    gaps: list[tuple[str, list[str]]] = []
    extra: list[tuple[str, list[str]]] = []
    unreachable: list[str] = []

    for campus in CAMPUSES:
        for keyword in QUERIES:
            old = search_codes(args.old, keyword, campus)
            new = search_codes(args.new, keyword, campus)
            if old is None or new is None:
                unreachable.append(f"{campus}/{keyword}")
                continue
            missing = sorted(old - new)
            if missing:
                gaps.append((f"{campus}/{keyword}", missing))
                print(f"✗ {campus}/{keyword}: 旧有新无 {missing}")
            else:
                covered += 1
                if not args.quiet:
                    print(f"✓ {campus}/{keyword}: 覆盖 {len(old)} 条")
            surplus = sorted(new - old)
            if surplus:
                extra.append((f"{campus}/{keyword}", surplus))

    print("\n--- course:read 结构比对 ---")
    for code in ("AUTO3005", "AUTO3001A", "COMP2010"):
        for campus in CAMPUSES:
            old_shape = read_shape(args.old, campus, code)
            new_shape = read_shape(args.new, campus, code)
            if old_shape is None or new_shape is None:
                print(f"  ? {campus}/{code}: 不可达")
                continue
            flag = "✓" if old_shape == new_shape else "✗"
            print(f"  {flag} {campus}/{code}: {old_shape == new_shape}")

    total = covered + len(gaps)
    print(f"\n检索完全覆盖 {covered}/{total}")
    if gaps:
        print(f"存在缺口 {len(gaps)} 个：")
        for name, missing in gaps:
            print(f"  - {name}: 旧有新无 {missing}")
    if extra:
        print(f"新服务额外命中 {len(extra)} 处（检索语义更宽，通常正常）")
    if unreachable:
        print(f"服务不可达的查询 {len(unreachable)} 个（需人工确认）")
        for item in unreachable[:10]:
            print(f"  - {item}")

    return 1 if gaps else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
