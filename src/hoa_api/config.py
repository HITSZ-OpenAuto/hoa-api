"""运行期配置，全部来自环境变量，便于 systemd / 容器部署。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    """服务配置。"""

    # 数据源
    org: str = os.getenv("HOA_ORG", "HITSZ-OpenAuto")
    github_token: str | None = os.getenv("GITHUB_TOKEN") or None
    site_origin: str = os.getenv("HOA_SITE_ORIGIN", "https://hoa.moe")
    api_base_path: str = os.getenv("HOA_API_BASE_PATH", "/api/v1")
    mcp_path: str = os.getenv("HOA_MCP_PATH", "/mcp")

    # 存储
    db_path: str = os.getenv("HOA_DB_PATH", "data/hoa.db")

    # 服务
    host: str = os.getenv("HOA_HOST", "0.0.0.0")
    port: int = _env_int("HOA_PORT", 8099)
    rate_limit_per_min: int = _env_int("HOA_RATE_LIMIT_PER_MIN", 60)
    cors_origins: str = os.getenv("HOA_CORS_ORIGINS", "*")

    # 同步
    sync_interval_sec: int = _env_int("HOA_SYNC_INTERVAL_SEC", 6 * 3600)
    sync_plans: bool = _env_bool("HOA_SYNC_PLANS", True)
    sync_materials: bool = _env_bool("HOA_SYNC_MATERIALS", True)
    user_agent: str = os.getenv(
        "HOA_USER_AGENT", "hoa-api/1.0 (+https://github.com/HITSZ-OpenAuto)"
    )

    # 写操作（v2）
    write_token: str | None = os.getenv("HOA_WRITE_TOKEN") or None

    @property
    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if raw == "*":
            return ["*"]
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def public_base_url(self) -> str:
        return f"{self.site_origin.rstrip('/')}{self.api_base_path}"


_config: Config | None = None


def get_config() -> Config:
    """返回进程级单例配置。"""
    global _config
    if _config is None:
        _config = Config()
    return _config
