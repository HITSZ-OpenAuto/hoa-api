#!/usr/bin/env python3
"""导出 FastAPI 生成的 OpenAPI 契约到 docs/openapi.yaml。

CI 会重新生成并比对，确保仓库里的契约与实现不漂移。
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hoa_api.api import create_app  # noqa: E402
from hoa_api.config import Config  # noqa: E402
from hoa_api.db import Store  # noqa: E402


def main() -> int:
    target = ROOT / "docs" / "openapi.yaml"
    store = Store(":memory:")
    app = create_app(Config(db_path=":memory:"), store)
    schema = app.openapi()
    schema["info"]["title"] = "HITSZ OpenAuto (HOA) Public API"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        yaml.safe_dump(schema, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )
    print(f"已写入 {target}")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
