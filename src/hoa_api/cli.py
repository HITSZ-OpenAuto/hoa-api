"""命令行入口：`hoa-api serve | sync | stats | check`。"""

from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from typing import Any

from .config import get_config
from .db import Store

logger = logging.getLogger("hoa_api")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api import create_app

    config = get_config()
    app = create_app(config)

    if not args.no_sync:
        _start_scheduler(config)

    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level="debug" if args.verbose else "info",
        access_log=True,
    )
    return 0


def _start_scheduler(config: Any) -> None:
    """在后台线程里周期性同步数据。"""

    def loop() -> None:
        from .sync import SyncPipeline

        while True:
            try:
                store = Store(config.db_path)
                pipeline = SyncPipeline(store, config)
                report = pipeline.run()
                store.set_meta("data_commit", str(report.as_dict()))
                logger.info("定时同步完成: %s", report.as_dict())
                pipeline.close()
                store.close()
            except Exception:
                logger.exception("定时同步失败")
            time.sleep(config.sync_interval_sec)

    thread = threading.Thread(target=loop, name="hoa-sync", daemon=True)
    thread.start()
    logger.info("后台同步线程已启动，间隔 %ss", config.sync_interval_sec)


def cmd_sync(args: argparse.Namespace) -> int:
    from .sync import SyncPipeline

    config = get_config()
    store = Store(config.db_path)
    pipeline = SyncPipeline(store, config)
    try:
        report = pipeline.run(
            limit=args.limit,
            include_major_data=not args.no_major_data,
        )
    finally:
        pipeline.close()
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    store.close()
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    from .service import Service

    config = get_config()
    store = Store(config.db_path)
    service = Service(store, config)
    print(json.dumps(service.meta(), ensure_ascii=False, indent=2))
    store.close()
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """自检：确认数据库可用、API 可路由、MCP 可列出工具。"""
    import asyncio

    from .api import create_app

    config = get_config()
    store = Store(config.db_path)
    app = create_app(config, store)

    schema = app.openapi()
    print("REST 路由:")
    for path, methods in sorted(schema.get("paths", {}).items()):
        verb = "/".join(sorted(m.upper() for m in methods if m != "parameters"))
        print(f"  {verb:8} {path}")

    async def list_tools() -> list[str]:
        from .mcp_server import build_mcp
        from .service import Service

        mcp = build_mcp(Service(store, config), config)
        tools = await mcp.list_tools()
        return [tool.name for tool in tools]

    tools = asyncio.run(list_tools())
    print("\nMCP 工具:")
    for name in tools:
        print(f"  {name}")
    store.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hoa-api", description="HITSZ OpenAuto 官方 API 与 MCP Server")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="启动 API + MCP 服务")
    serve.add_argument("--no-sync", action="store_true", help="关闭后台定时同步")
    serve.set_defaults(func=cmd_serve)

    sync = sub.add_parser("sync", help="立即执行一次数据同步")
    sync.add_argument("--limit", type=int, default=None, help="只同步前 N 个课程仓")
    sync.add_argument("--no-major-data", action="store_true", help="跳过成绩与培养方案同步")
    sync.set_defaults(func=cmd_sync)

    stats = sub.add_parser("stats", help="查看数据统计")
    stats.set_defaults(func=cmd_stats)

    check = sub.add_parser("check", help="自检：路由与 MCP 工具清单")
    check.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
