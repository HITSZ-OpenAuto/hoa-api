# 部署指南

两条路径：

- **A. 官方部署（推荐）**：GitHub Actions 构建镜像 → 官方 VPS 的 Docker → Traefik 反代。凭据复用 `HITSZ-OpenAuto/hoa-fuma` 的仓库级 secret。
- **B. 自托管**：任意 Debian / OpenCloudOS 机器，systemd + nginx，适用于没有官方 VPS 访问权的场景。

---

## A. 官方部署

### A1. 官方 VPS 的真实拓扑（已实测确认）

改任何路由配置前请先核对这一节，避免按错误的假设改：

| 项 | 实测值 |
| --- | --- |
| 服务器 | `kowyo@100.113.37.19`（Tailscale），公网 IP `77.42.21.198` |
| 容器运行时 | Docker（rootless），网络 `proxy`（`172.18.0.0/16`） |
| 反向代理 | Traefik v3.7.16，compose 项目 `traefik-compose`，配置在 `/home/kowyo/traefik-compose/` |
| Provider | **仅 file provider**：`--providers.file.directory=/etc/traefik/dynamic`，宿主目录 `/home/kowyo/traefik-compose/dynamic` |
| Docker provider | **未启用** → 容器标签不产生任何路由 |
| 证书 | Let's Encrypt，resolver 名 `le`，HTTP-01 challenge 走 80 端口 |
| 现有路由 | `dynamic/memos.yml`、`dynamic/stats.yml`、`dynamic/uptime.yml` |
| `hoa.moe` 本身 | 走 **Cloudflare Tunnel**（`cloudflared` → `http://localhost:19800` → hoa-fuma），**不经 Traefik** |
| 已有端口 | 80/443（Traefik）、19800（hoa-fuma）、19801（hoa-api） |

两个容易踩的坑：

1. **Traefik 的 router 一旦带 `tls` 段，就只会绑定到 TLS entrypoint**，不会同时监听 80 端口。要同时提供 HTTP 与 HTTPS，必须写两个独立 router。
2. **远端默认 shell 是 `zsh`**，且 `appleboy/ssh-action` 用 `zsh -c` 执行脚本。`$GITHUB_OUTPUT` 是 runner 端变量，远端不存在，脚本里引用它会在 `set -u` 下直接失败。远端脚本统一用 `bash <<'BASH_EOF' ... BASH_EOF` 包裹。

### A2. 触发部署

```bash
# 由调用方仓库 hoa-fuma 触发（凭据在 hoa-fuma，代码在 hoa-api）
gh workflow run deploy-hoa-api.yml -R HITSZ-OpenAuto/hoa-fuma --ref main

# 查看任务状态
gh run view <RUN_ID> -R HITSZ-OpenAuto/hoa-fuma \
  --json jobs --jq '.jobs[] | "\(.name): \(.status) \(.conclusion // "-")"'
```

五个任务：`构建并推送镜像` → `探测 VPS 环境` → `配置 Cloudflare DNS` → `部署到官方 VPS` → `外网验证`。

工作流位于 `HITSZ-OpenAuto/hoa-api/.github/workflows/deploy.yml`，是可复用工作流（`workflow_call`），由 hoa-fuma 的 `deploy-hoa-api.yml` 以 `secrets: inherit` 调用——**代码留在 hoa-api，凭据留在 hoa-fuma**。

### A3. 部署做了什么

1. **构建镜像**：`ghcr.io/hitsz-openauto/hoa-api`，同时推 `latest` 与 `build-<run>-<attempt>` 两个标签，部署使用不可变的 build 标签。
2. **探测环境**：加入组织 Tailscale 网络；推导源站公网 IP；打印容器清单与 Traefik 动态配置目录。
3. **写 DNS**：调用 Cloudflare API 写 A 记录。若 token 无 DNS 权限则**降级为人工指引**（不阻断流程）。该 token 目前具备清缓存权限但无 DNS 编辑权限。
4. **部署容器**：
   ```bash
   docker run -d --name hoa-api --network proxy --restart unless-stopped \
     -p 19801:8099 -v hoa-api-data:/app/data \
     -e GITHUB_TOKEN=... -e HOA_MCP_ALLOWED_HOSTS=... \
     ghcr.io/hitsz-openauto/hoa-api:build-N-M
   ```
   数据落在 Docker 卷 `hoa-api-data`，重建容器不丢数据。
5. **写 Traefik 路由**：生成 `dynamic/hoa-api.yml` 并原子替换（先写 `.tmp` 再 `mv`），Traefik file provider 自动热加载。每个域名两个 router：
   ```yaml
   http:
     routers:
       hoa-api-api-hoa-moe:          # HTTP(80)，证书签发前也可访问
         rule: "Host(`api.hoa.moe`)"
         entryPoints: ["web"]
         service: hoa-api-svc-api-hoa-moe
       hoa-api-tls-api-hoa-moe:       # HTTPS(443)，Traefik 自动签证书
         rule: "Host(`api.hoa.moe`)"
         entryPoints: ["websecure"]
         service: hoa-api-svc-api-hoa-moe
         tls:
           certResolver: le
     services:
       hoa-api-svc-api-hoa-moe:
         loadBalancer:
           servers:
             - url: "http://hoa-api:8099"
   ```
   服务地址用容器名 `hoa-api`，由 Docker 内嵌 DNS 在 `proxy` 网络内解析。
6. **验证**：经 Tailscale 直连源站（`curl -H "Host: api.hoa.moe" http://100.113.37.19/api/v1/meta`）与 MCP `tools/list`，两者都必须是 200；再尝试公网域名。

### A4. DNS 记录

需要在 Cloudflare 添加：

| 类型 | 名称 | 指向 | 代理 |
| --- | --- | --- | --- |
| A | `api.hoa.moe` | `77.42.21.198` | 开启（橙云） |
| A | `hoa-api.limpu.cn` | `77.42.21.198` | 视需要（不开代理则直连源站） |

DNS 生效后，Traefik 会在收到该域名的 TLS 请求时自动通过 Let's Encrypt 签发证书（HTTP-01 走 80 端口），无需手动干预。首次签发通常需要几十秒。

> `api.hoa.moe` 走 Cloudflare 橙云时，回源到源站 443；`hoa-api.limpu.cn` 若不开代理则是浏览器直连源站，证书同样由 Traefik 签发。

**没有 DNS 权限时的临时入口**：可以额外挂一个 IP 型公共域名（例如 `77.42.21.198.sslip.io`，
由 sslip.io 按 IP 自动解析，不需要任何账户或 DNS 权限）。把它加进调用方的
`additional_domains` 即可，Traefik 会照样通过 Let's Encrypt 签发真实证书：

```yaml
additional_domains: hoa-api.limpu.cn,77.42.21.198.sslip.io
```

实测该域名的证书为 `issuer: C=US; O=Let's Encrypt; CN=YR1`，全部 REST 与 MCP 接口返回 200。
官方 A 记录加好后，从 `additional_domains` 里移除这个临时域名即可。

### A5. 验证

```bash
# 源站（不依赖 DNS）
curl -s -H 'Host: api.hoa.moe' http://100.113.37.19/api/v1/meta

# 公网
curl -s https://api.hoa.moe/api/v1/meta

# MCP
curl -s -X POST https://api.hoa.moe/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

---

## B. 自托管（systemd + nginx）

### B1. 准备

```bash
python3.11 --version
git clone https://github.com/HITSZ-OpenAuto/hoa-api.git /root/hoa-api
cd /root/hoa-api
python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .
```

### B2. 配置

```bash
cp .env.example .env
vi .env
```

| 变量 | 说明 |
| --- | --- |
| `GITHUB_TOKEN` | **必填**。匿名 GitHub API 配额只有 60 次/小时，无法完成 152 个课程仓的全量同步 |
| `HOA_DB_PATH` | SQLite 路径，目录需可写 |
| `HOA_PORT` | 监听端口，默认 8099 |
| `HOA_SYNC_INTERVAL_SEC` | 同步间隔，默认 21600（6 小时） |
| `HOA_MCP_ALLOWED_HOSTS` | 反代后的 Host 白名单，防 DNS 重绑定 |

### B3. 首次同步

```bash
cd /root/hoa-api
.venv/bin/hoa-api sync
```

预期输出：

```json
{
  "courses_total": 152,
  "courses_updated": 152,
  "courses_failed": 0,
  "materials": 6133,
  "grades": 118,
  "plans": 313
}
```

> 首次同步约需 5–10 分钟（依赖 GitHub API 响应速度）。后续同步走 ETag 条件请求，通常 1–2 分钟。

### B4. systemd

```bash
cp deploy/hoa-api.service /etc/systemd/system/hoa-api.service
mkdir -p /root/hoa-api/data
systemctl daemon-reload
systemctl enable --now hoa-api
systemctl status hoa-api
journalctl -u hoa-api -f
```

### B5. nginx 反代

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
- 反代后必须设置 `HOA_MCP_ALLOWED_HOSTS`，否则 MCP 的 Host 校验会拒绝请求

### B6. 验证

```bash
curl -s localhost:8099/api/v1/meta | python3 -m json.tool
curl -s 'localhost:8099/api/v1/courses?q=自动控制&limit=3' | python3 -m json.tool

curl -s -X POST localhost:8099/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
        "protocolVersion":"2025-06-18",
        "capabilities":{},
        "clientInfo":{"name":"curl","version":"1.0"}}}'
```

---

## C. 运维

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

官方部署则备份 Docker 卷：

```bash
docker run --rm -v hoa-api-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/hoa-api-data-$(date +%F).tar.gz -C /data .
```

也可只备份原始数据源（GitHub 上的课程仓本身即 SSOT），本地库可随时用 `hoa-api sync` 重建。

### 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 同步大量 `403` | `GITHUB_TOKEN` 过期或权限不足 | 换新 token，确认含 `public_repo` |
| 同步报 `GitHub API rate limit exceeded` | 匿名配额 | 配置 token |
| MCP `initialize` 返回 404 | nginx 未关闭缓冲 / 路径不对 | 检查 `location = /mcp` 与 `proxy_buffering off;` |
| MCP 返回 `Invalid Host header` | 反代后 Host 未加入白名单 | 设置 `HOA_MCP_ALLOWED_HOSTS` |
| Traefik 对新域名返回 404 | router 带 `tls` 段只绑定 TLS entrypoint，或文件未热加载 | 拆成 HTTP/HTTPS 两个 router；确认文件在 `dynamic/` 目录内 |
| 远端脚本报 `GITHUB_OUTPUT: parameter not set` | 远端是 zsh，该变量只存在于 runner | 远端脚本用 `bash <<'BASH_EOF'` 包裹，或改用 workflow input 传值 |
| `429` 频繁 | 触发限流 | 提高 `HOA_RATE_LIMIT_PER_MIN`，或使用 API Key（v2） |
