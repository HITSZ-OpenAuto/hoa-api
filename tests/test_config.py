"""配置项测试。"""

from __future__ import annotations

from hoa_api.config import Config


def test_mcp_allowed_hosts_include_port_wildcards():
    """Host 白名单必须补上 ``:*`` 通配。

    MCP SDK 的 Host 校验是「精确匹配」或「``host:*`` 通配」，不会自动去掉端口。
    HTTP 的 Host 头在非默认端口上必然带端口（``127.0.0.1:8099``），
    只写裸主机名会让所有直连访问被 DNS 重绑定防护拒成 421。
    """
    config = Config(
        db_path=":memory:",
        mcp_allowed_hosts="localhost,127.0.0.1,[::1],api.hoa.moe",
    )
    hosts = config.mcp_allowed_host_list

    for host in ("localhost", "127.0.0.1", "[::1]", "api.hoa.moe"):
        assert host in hosts
        assert f"{host}:*" in hosts

    # 已显式指定端口的条目不再补通配
    explicit = Config(db_path=":memory:", mcp_allowed_hosts="example.com:8443")
    assert explicit.mcp_allowed_host_list == ["example.com:8443"]

    # 空串与多余空白被忽略
    messy = Config(db_path=":memory:", mcp_allowed_hosts=" a.com , , b.com ")
    assert messy.mcp_allowed_host_list == ["a.com", "a.com:*", "b.com", "b.com:*"]


def test_compat_rate_limit_is_wider_than_public():
    """兼容层限流阈值必须大于公开 API。

    旧 course-server 只在 localhost 提供服务且不限流，HIT-A 切过来后
    不应因为公开 API 的阈值拿到 429。
    """
    config = Config(db_path=":memory:", rate_limit_per_min=120)
    assert config.compat_rate_limit_per_min == 1200

    override = Config(
        db_path=":memory:", rate_limit_per_min=60, compat_rate_limit_per_min_override=5000
    )
    assert override.compat_rate_limit_per_min == 5000


def test_public_origin_defaults_to_site_origin():
    """未显式配置时，API 的对外地址跟随站点地址。"""
    config = Config(db_path=":memory:", site_origin="https://hoa.moe")
    assert config.public_base_url == "https://hoa.moe/api/v1"
    assert config.public_mcp_url == "https://hoa.moe/mcp"

    explicit = Config(
        db_path=":memory:",
        site_origin="https://hoa.moe",
        public_origin="https://api.hoa.moe",
    )
    assert explicit.public_base_url == "https://api.hoa.moe/api/v1"
    assert explicit.public_mcp_url == "https://api.hoa.moe/mcp"
