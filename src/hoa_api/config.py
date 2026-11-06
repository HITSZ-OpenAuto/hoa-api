"""运行期配置，全部来自环境变量，便于 systemd / 容器部署。"""

from __future__ import annotations

import os
from dataclasses import dataclass


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
    # API 自身的对外地址。默认跟随站点地址，独立部署时应显式指定，
    # 否则 /api/v1/meta 里给出的 base_url / mcp_endpoint 会指向站点而不是 API。
    public_origin: str = os.getenv("HOA_PUBLIC_ORIGIN", "")
    mcp_allowed_hosts: str = os.getenv(
        "HOA_MCP_ALLOWED_HOSTS",
        "localhost,127.0.0.1,[::1],api.hoa.moe,api.hita.limpu.cn",
    )
    mcp_allowed_origins: str = os.getenv("HOA_MCP_ALLOWED_ORIGINS", "")

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
    def mcp_allowed_host_list(self) -> list[str]:
        return [item.strip() for item in self.mcp_allowed_hosts.split(",") if item.strip()]

    @property
    def mcp_allowed_origin_list(self) -> list[str]:
        return [item.strip() for item in self.mcp_allowed_origins.split(",") if item.strip()]

    @property
    def public_origin_url(self) -> str:
        """API 的对外访问根地址；未显式配置时跟随站点地址。"""
        return (self.public_origin or self.site_origin).rstrip("/")

    @property
    def public_base_url(self) -> str:
        return f"{self.public_origin_url}{self.api_base_path}"

    @property
    def public_mcp_url(self) -> str:
        return f"{self.public_origin_url}{self.mcp_path}"


_config: Config | None = None


def get_config() -> Config:
    """返回进程级单例配置。"""
    global _config
    if _config is None:
        _config = Config()
    return _config
