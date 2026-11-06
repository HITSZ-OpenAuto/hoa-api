# HIT-A 迁移说明：course-server → hoa-api

目标：让 HIT-A 的 agent 改为消费 **HITSZ-OpenAuto 官方 API**，而不是直连私有 `course-server` 读 HITSZ-OpenAuto 的仓库。

---

## 1. 现状

```
HIT-A agent-backend (Go, :8080)
        │  COURSE_SERVER_URL=http://localhost:8081
        ▼
course-server / pr-server (Go, :8081)   ← 私有仓库 HIT-A/data-backend
        │  直接读 HITSZ-OpenAuto 的 155 个课程仓
        ▼
HITSZ-OpenAuto/<COURSE_CODE> 仓库
```

`agent-backend` 里有三处使用这个地址（`internal/courseclient/courseclient.go:23`、`internal/skills/course_skills.go:205`、`internal/ai/tools.go:400`）：

```go
base := envFirst("COURSE_SERVER_URL", "PR_SERVER_URL")
if base == "" { base = "http://localhost:8081" }
```

实际配置在 `/root/agent-backend/config/agent-backend.env`：

```bash
COURSE_SERVER_URL=http://localhost:8081
```

`course-server` 当前暴露的端点：

| 端点 | 职责 | 归属判断 |
| --- | --- | --- |
| `POST /v1/courses:search` | 检索 HOA 课程 | **应迁到 HOA 官方 API** |
| `POST /v1/course:read` | 读取 HOA 课程 README | **应迁到 HOA 官方 API** |
| `POST /v1/course:preview` | 预览 TOML ops 改动 | 写入路径，暂留 |
| `POST /v1/course:submit` | 提交 PR | 写入路径，暂留 |
| `POST /v1/pr:lookup` | 查询 PR 状态 | 写入路径，暂留 |

---

## 2. 迁移后

```
HIT-A agent-backend (Go, :8080)
        │  COURSE_SERVER_URL=http://127.0.0.1:8099   ← 只改这一行
        ▼
hoa-api (Python/FastAPI, :8099)                      ← HITSZ-OpenAuto 官方仓库
        │
        ▼
HITSZ-OpenAuto/<COURSE_CODE> 仓库（定期同步进 SQLite）
```

`hoa-api` 的 `/v1` 兼容层**逐字节复刻**了 `course-server` 的响应信封：

```jsonc
// POST /v1/courses:search
{ "ok": true, "data": { "results": [ { "code", "name", "org", "repo", "teachers", "aliases" } ] } }

// POST /v1/course:read
{ "ok": true, "data": { "base": { "org", "cache_org", "repo", "ref", "toml_path", "repo_type" },
                         "result": { "readme_md", "readme_toml" } } }
```

因此 **agent-backend 与其下游（HITA App、AstrBot 插件、bot-backend）无需任何代码改动**。

---

## 3. 切换步骤

### 3.1 部署 hoa-api（先不动 HIT-A）

```bash
git clone https://github.com/HITSZ-OpenAuto/hoa-api.git /root/hoa-api
cd /root/hoa-api
python3.11 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env && vi .env      # 填入 GITHUB_TOKEN
.venv/bin/hoa-api sync               # 首次全量同步
systemctl enable --now hoa-api
```

### 3.2 灰度验证

```bash
# 读路径与老实现对比
curl -s localhost:8099/v1/courses:search -H 'Content-Type: application/json' \
  -d '{"keyword":"自动控制","limit":5}'
curl -s localhost:8081/v1/courses:search -H 'Content-Type: application/json' \
  -d '{"keyword":"自动控制","limit":5}'
```

两者的 `data.results` 应对齐（字段集合一致；`hoa-api` 额外保证 `teachers`/`aliases` 非空）。

### 3.3 切换

编辑 `/root/agent-backend/config/agent-backend.env`：

```diff
-COURSE_SERVER_URL=http://localhost:8081
+COURSE_SERVER_URL=http://127.0.0.1:8099
```

```bash
systemctl restart agent-backend
systemctl status agent-backend
```

### 3.4 验证

```bash
# agent-backend 的 skill 网关
curl -s localhost:8080/v1/skills | python3 -m json.tool | head -40

# 直接打 agent-backend 的课程 skill
curl -s localhost:8080/v1/skills/courses.search:invoke \
  -H 'Content-Type: application/json' \
  -d '{"input":{"keyword":"机器人学导论","limit":3}}'
```

---

## 4. 行为差异（需要留意）

| 差异点 | course-server | hoa-api | 影响 |
| --- | --- | --- | --- |
| 传输方法 | POST | POST（兼容层） | 无 |
| 数据新鲜度 | 实时读 GitHub（受 GitHub API 配额与延迟影响） | SQLite 快照，默认 6 小时同步一次 | 刚上传的资料最多滞后一个同步周期 |
| 失败语义 | 网关超时 / GitHub 错误 | 统一 `{ok:false, error:{code,message}}` | 错误信息更规范 |
| 跨校区 | 支持 shenzhen / harbin / weihai | **当前仅深圳（HOA）** | HIT-A 若用到哈工大本部/威海校区需保留旧路径 |
| 缓存 | `cache_org` 回退（HOA-Cache） | 直读 HITSZ-OpenAuto | 旧回退仓不再需要 |

> 跨校区是唯一的**功能性缺口**。如果 HIT-A 的 `hit.teachers` 等 skill 依赖本部/威海数据，
> 迁移时应把 `COURSE_SERVER_URL` 切走、同时把 `PR_SERVER_URL` 保留给 `course-server`，
> 让读路径走 HOA 官方 API、写路径与跨校区仍走旧服务。

---

## 5. 写入路径的未来归属

`course:preview` / `course:submit` 目前依赖 `course-server` 的
`internal/tomlops`、`internal/render`（TOML → README 渲染），
以及 `repos-management` 的同名脚本（`convert_toml_to_readme.py`）。

推荐路径（与现有组织分工一致）：

1. **结构化编辑逻辑**留在 `HITSZ-OpenAuto/repos-management`（它本来就是 TOML↔README 的 SSOT）；
2. `hoa-api` 只提供**事务编排**：校验 ops → 调 GitHub API 建分支/提交/PR；
3. HIT-A 的 `pr-server` 退化为薄适配层，或直接下线。

这样「读」与「写」都归 HITSZ-OpenAuto，HIT-A 只保留自己的业务逻辑（教师爬取、RAG、聚合搜索）。

---

## 6. 回滚

```bash
sed -i 's|COURSE_SERVER_URL=.*|COURSE_SERVER_URL=http://localhost:8081|' \
  /root/agent-backend/config/agent-backend.env
systemctl restart agent-backend
```

`hoa-api` 可随时 `systemctl stop hoa-api`，不影响 HIT-A 现有链路。
