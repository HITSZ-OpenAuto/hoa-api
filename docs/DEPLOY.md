# 部署指南

以 Debian / OpenCloudOS + systemd + nginx 为例（服务器无 Docker 时同样适用）。

## 1. 准备

```bash
# 依赖：Python 3.11+
python3.11 --version

git clone https://github.com/HITSZ-OpenAuto/hoa-api.git /root/hoa-api
cd /root/hoa-api

python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .
```

## 2. 配置

```bash
cp .env.example .env
vi .env
```

关键项：

| 变量 | 说明 |
| --- | --- |
| `GITHUB_TOKEN` | **必填**。匿名 GitHub API 配额只有 60 次/小时，无法完成 149 个课程仓的全量同步 |
| `HOA_DB_PATH` | SQLite 路径，目录需可写 |
| `HOA_PORT` | 监听端口，默认 8099 |
| `HOA_SYNC_INTERVAL_SEC` | 同步间隔，默认 21600（6 小时） |

## 3. 首次同步

```bash
cd /root/hoa-api
.venv/bin/hoa-api sync
```

预期输出：

```json
{
  "courses_total": 149,
  "courses_updated": 149,
  "courses_failed": 0,
  "materials": 20000,
  "grades": 118,
  "plans": 313
}
```

> 首次同步约需 5–10 分钟（依赖 GitHub API 响应速度）。后续同步走 ETag 条件请求，通常 1–2 分钟。

## 4. systemd

```bash
cp deploy/hoa-api.service /etc/systemd/system/hoa-api.service
mkdir -p /root/hoa-api/data
systemctl daemon-reload
systemctl enable --now hoa-api
systemctl status hoa-api
journalctl -u hoa-api -f
```

## 5. nginx 反代

```bash
cp deploy/nginx.conf.example /etc/nginx/conf.d/hoa-api.conf
# 修改 server_name 与证书路径
certbot --nginx -d api.hoa.moe
nginx -t && systemctl reload nginx
```

要点：

- MCP 的 Streamable HTTP 走 SSE，必须 `proxy_buffering off;`
- 读接口有 5 分钟 CDN 友好缓存（`Cache-Control: public, max-age=300`）
- 建议给 `/api/v1/*` 加 `proxy_cache` 以降低源站压力

## 6. 验证

```bash
# 健康与元信息
curl -s localhost:8099/api/v1/meta | python3 -m json.tool

# 课程检索
curl -s 'localhost:8099/api/v1/courses?q=自动控制&limit=3' | python3 -m json.tool

# MCP 握手（initialize）
curl -s -X POST localhost:8099/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
        "protocolVersion":"2025-06-18",
        "capabilities":{},
        "clientInfo":{"name":"curl","version":"1.0"}}}'

# MCP 列出工具
curl -s -X POST localhost:8099/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

## 7. 运维

```bash
.venv/bin/hoa-api stats     # 数据规模快照
.venv/bin/hoa-api check     # 路由与 MCP 工具自检
.venv/bin/hoa-api sync      # 手动触发同步
```

### 备份

数据是 SQLite 单文件，直接备份即可：

```bash
sqlite3 /root/hoa-api/data/hoa.db ".backup /root/hoa-backup-$(date +%F).db"
```

也可只备份原始数据源（GitHub 上的课程仓本身即 SSOT），本地库可随时用 `hoa-api sync` 重建。

### 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 同步大量 `403` | `GITHUB_TOKEN` 过期或权限不足 | 换新 token，确认含 `public_repo` |
| 同步报 `GitHub API rate limit exceeded` | 匿名配额 | 配置 token |
| MCP `initialize` 返回 404 | nginx 未关闭缓冲 / 路径不对 | 检查 `location = /mcp` 与 `proxy_buffering off` |
| `429` 频繁 | 触发限流 | 提高 `HOA_RATE_LIMIT_PER_MIN`，或使用 API Key（v2） |
