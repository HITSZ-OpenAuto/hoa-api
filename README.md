# HOA API

**HITSZ OpenAuto 官方 API 与 MCP Server** —— 把 [HITSZ-OpenAuto](https://github.com/HITSZ-OpenAuto) 组织下 155 个公开课程仓的数据，以**官方、公开、版本化**的 REST API 和 MCP Server 暴露给任意 Agent。

- 站点：[hoa.moe](https://hoa.moe)
- 组织：[HITSZ-OpenAuto](https://github.com/HITSZ-OpenAuto)
- 契约版本：`v1`

## 为什么存在

HOA 的数据是公共资产，但此前**没有官方接口层**：

- 站点只有一个内部的 `/api/search`，没有结构化 schema，不可编程消费；
- HIT-A 的私有 `course-server`（Go）实际上已经在直读 HITSZ-OpenAuto 的仓库，并对外提供 `POST /v1/courses:search`、`POST /v1/course:read`；
- 那份契约散落在 HIT-A 的私有仓库里，没有版本、没有 OpenAPI、社区无法 review，文档中的仓库名甚至已经过时。

本服务把这层接口**扶正**到数据所属的组织：契约进仓库、版本化、公开，HIT-A 反过来成为它的客户端。

## 能力一览

### REST API（`/api/v1`）

| 端点 | 说明 |
| --- | --- |
| `GET /api/v1/courses` | 课程检索（关键词 / 教师 / 专业 / 年级） |
| `GET /api/v1/courses/{code}` | 课程完整信息（章节、教师评价、成绩构成、学时学分） |
| `GET /api/v1/courses/{code}/readme?format=md\|toml` | 原始 README（`readme.toml` 为事实来源） |
| `GET /api/v1/courses/{code}/materials` | 资料文件树（试卷 / 作业 / 实验 / 笔记 / 课件） |
| `GET /api/v1/teachers` | 教师索引 |
| `GET /api/v1/grades` · `/api/v1/grades/{code}` | 成绩构成 |
| `GET /api/v1/plans` · `/api/v1/plans/{year}/{major}` | 培养方案 |
| `GET /api/v1/search` | 统一检索 |
| `GET /api/v1/meta` | 版本、快照时间、数据规模 |
| `GET /api/v1/docs` | Swagger UI |

### 兼容层（`/v1`）

为 HIT-A `course-server` 保持不变的 POST 接口，可直接把 `COURSE_SERVER_URL` 指向本服务：

- `POST /v1/courses:search`
- `POST /v1/course:read`

响应信封与老实现完全一致（`{ok, data:{base, result}}`），下游无需改动。

### MCP Server（`/mcp`）

Streamable HTTP（无状态模式），工具：

| 工具 | 作用 |
| --- | --- |
| `search_courses` | 检索课程 |
| `get_course` | 课程详情 |
| `get_course_readme` | 原始 README |
| `get_course_materials` | 资料文件树 |
| `list_teachers` | 教师与所授课程 |
| `get_grading` | 成绩构成 |
| `get_curriculum_plan` | 培养方案 |
| `search_site` | 统一检索 |

资源：`hoa://course/{code}`、`hoa://course/{code}/readme`、`hoa://teacher/{name}`、`hoa://plan/{year}/{major}`

客户端配置：

```json
{
  "mcpServers": {
    "hoa": { "type": "http", "url": "https://<host>/mcp" }
  }
}
```

## 数据来源

| 数据 | 来源 |
| --- | --- |
| 课程内容 | 各课程仓的 `readme.toml`（**事实来源**），`README.md` 为渲染副本 |
| 资料目录 | 课程仓的 `assignments/ exams/ labs/ notes/ slides/` |
| 成绩构成 | [`hoa-major-data`](https://github.com/HITSZ-OpenAuto/hoa-major-data) `grades_summary.json` |
| 培养方案 | `hoa-major-data/plans/*.toml` |
| 课程代码别名 | `hoa-major-data/lookup_table.toml`（教务码 → 仓库 ID） |
| 课程仓清单 | [`repos-management`](https://github.com/HITSZ-OpenAuto/repos-management) `repos_list.txt` |

同步策略：`readme.toml` / `README.md` 走 raw.githubusercontent（无 API 配额）；目录树与 commit 走 api.github.com（带 ETag 条件请求，304 不计配额）。默认每 6 小时增量同步一次。

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/API.md](docs/API.md) | REST 与 MCP 完整参考 |
| [docs/DESIGN.md](docs/DESIGN.md) | 方案设计（为什么做、数据模型、架构取舍） |
| [docs/DEPLOY.md](docs/DEPLOY.md) | 部署指南（systemd + nginx） |
| [docs/MIGRATION-HIT-A.md](docs/MIGRATION-HIT-A.md) | HIT-A `course-server` 迁移说明 |
| [docs/openapi.yaml](docs/openapi.yaml) | OpenAPI 契约（由实现导出，CI 校验不漂移） |

## 快速开始

```bash
# 安装
uv venv --python 3.11 .venv
uv pip install -e .

# 首次同步（需要 GITHUB_TOKEN 以获得足够的 API 配额）
export GITHUB_TOKEN=ghp_xxx
.venv/bin/hoa-api sync

# 启动服务（默认 0.0.0.0:8099）
.venv/bin/hoa-api serve
```

自检：

```bash
.venv/bin/hoa-api check     # 打印 REST 路由与 MCP 工具清单
```

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `HOA_DB_PATH` | `data/hoa.db` | SQLite 路径 |
| `HOA_HOST` / `HOA_PORT` | `0.0.0.0` / `8099` | 监听地址 |
| `HOA_API_BASE_PATH` | `/api/v1` | REST 前缀 |
| `HOA_MCP_PATH` | `/mcp` | MCP 端点 |
| `HOA_SITE_ORIGIN` | `https://hoa.moe` | 对外站点地址 |
| `HOA_RATE_LIMIT_PER_MIN` | `60` | 每 IP 每分钟请求上限 |
| `HOA_SYNC_INTERVAL_SEC` | `21600` | 同步间隔 |
| `GITHUB_TOKEN` | – | GitHub token，显著提升同步配额 |

## 部署

见 [`docs/DEPLOY.md`](docs/DEPLOY.md)：systemd + nginx 反代示例。

## 迁移说明

见 [`docs/MIGRATION-HIT-A.md`](docs/MIGRATION-HIT-A.md)：HIT-A `course-server` → 本服务的切换路径。

## License

MIT
