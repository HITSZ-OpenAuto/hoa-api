# HOA 官方 API + MCP 方案设计

> 目标：给 [HITSZ-OpenAuto](https://github.com/HITSZ-OpenAuto) 增加一套**官方、公开、版本化**的 REST API 与 MCP Server，
> 让 HIT-A 的 agent、以及任何第三方 Agent 都能稳定、合规地消费 HOA 的课程数据。

---

## 1. 为什么要做（问题诊断）

调研了双方仓库后，核心矛盾很清楚：**数据在 HITSZ-OpenAuto，接口却长在 HIT-A 的私有仓库里。**

| 事实 | 出处 | 后果 |
| --- | --- | --- |
| HOA 的全部课程内容分散在 155 个课程仓的 `readme.toml` + 资源目录 | `repos-management/repos_list.txt`（155 行）、`course-template/readme.toml` | 没有单一契约，Agent 只能逐仓爬 GitHub |
| HOA 侧**没有**对外 API，只有站点内部路由 `/api/search` 和 `llms.txt` | `hoa-fuma/app/api/search/route.ts`、`app/llms.txt/route.ts` | 搜索结果无结构化 schema，不可编程消费 |
| HIT-A 的私有 `pr-server`（Go）**已经**在读 HITSZ-OpenAuto 的仓库并提供 `POST /v1/courses:search`、`POST /v1/course:read` | `HIT-A/all_api/pr-Server-api/README.md` | 官方数据被私有服务代理，接口能力与组织归属错位 |
| HIT-A 的契约文档里课程仓库名仍是过时的 `hoa-courses-shenzhen` | `HIT-A/all_api/agent-backend-api/v1.md` 第 502 行 | 契约已腐化，下游随时踩坑 |
| `agent-backend` / `pr-server` **不在公开仓库列表**（私有） | `HIT-A` org 公开列表仅 12 个仓 | 第三方 Agent 无法接入；HITA App 以外的人拿不到任何接口 |
| HIT-A 的 33 个 skill 契约散落在 `all_api/agent-backend-api/`（v1.md + openapi.yaml + 41 篇 agent-guides） | `HIT-A/all_api/` | 契约与实现分离，SSOT 在私有仓，改动无法被社区 review |

**结论**：HOA 数据是公共资产（155 个公开仓、公开站点），但它的**官方接口层缺失**。HIT-A 的私有 `pr-server` 事实上已经承担了这个角色，只是没有契约公开、没有版本、没有归属。把它补正为 HITSZ-OpenAuto 官方 API + MCP，HIT-A 反过来降级为**客户端**，是目前成本最低、收益最高的路径。

---

## 2. 双方资产盘点

### 2.1 HITSZ-OpenAuto（数据侧，公开）

| 仓库 | 技术栈 | 作用 | 可否作为 API 数据源 |
| --- | --- | --- | --- |
| `hoa-backend` | Rust | **核心聚合器**：拉全部课程仓 → 生成 `content/docs/**` MDX（含 frontmatter、文件树、成绩构成、教师） | ✅ 已产出结构化快照 |
| `hoa-fuma` | Next.js 15 + Fumadocs | 站点 hoa.moe；已有 `/api/search`、`/llms.txt`、`/llms.mdx`、RSS、sitemap | ✅ 天然的 API 宿主 |
| `hoa-major-data` | JSON/TOML | `grades_summary.json`（118 门课成绩构成）、`lookup_table.toml`（教务码→仓库 ID）、`major_mapping.json`、`plans/*.toml`（培养方案） | ✅ 结构化直读 |
| `repos-management` | Python | `readme.toml ⇄ README.md` 双向转换、组织级 workflow、`repos_list.txt` 维护 | ⚠️ 转换逻辑可复用，但属工具链 |
| `hoa-skills` | Markdown | `hoa-contribute` 技能，教会 Agent 走 fork/clone/PR 贡献流程 | ❌ 非数据源，是写入路径的**文档** |
| `hoa-wiki` / `hoa-blog` / `hoa-news` | MDX | 参与指南、博客、资讯 | ✅ 可纳入搜索 |
| 155 个课程仓 | 各异 | `README.md`（渲染产物）+ `readme.toml`（**SSOT**）+ `assignments/ exams/ labs/ notes/ slides/` | ✅ 资源目录树 |

**`readme.toml` 实际 schema**（取自 `AUTO3005`，与 `course-template/readme.toml` 一致）：

```toml
course_name = "机器人学导论"
course_code = "AUTO3005"
repo_type  = "normal"          # normal | multi-project
description = """..."""

[lecturers]
[[lecturers.intro]]            # 教师团队简介（列表，在 items 之前）
[[lecturers.items]]            # 教师
name = "楼云江"
[[lecturers.items.reviews]]     # 评价
content = """..."""
author = { name = "昵称", date = "2025-03" }
[[lecturers.summary]]          # 教师总结（列表，在 items 之后）

[[sections]]                   # 自定义章节
title = "教材与在线资源"
[[sections.items]]
content = """..."""
author = { name = "昵称", date = "2025-03" }
```

> 关键约定：**`readme.toml` 是 SSOT，`README.md` 是渲染产物**（由 `repos-management` 的 `toml2md` 生成）。API 一律以 TOML 为准。

### 2.2 HIT-A（消费侧）

| 仓库 | 状态 | 说明 |
| --- | --- | --- |
| `all_api` | 公开 | API 契约包：`agent-backend-api/`（v1.md + openapi.yaml + 41 篇 agent-guides）、`pr-Server-api/`、`bot-backend-api/`、`school-api/` |
| `bot-backend` | 公开 | Bot 后端 |
| `astrbot_plugin_hit` | 公开 | AstrBot 插件（HITA 的 Agent 入口之一） |
| `HITA_RagData` / `DATA_*` | 公开 | RAG 数据集 |
| `HITA_Android` / `hita_omni` / `HITA_NEXT` / `hita-stats` | 公开 | 客户端与统计 |
| `agent-backend` | **私有** | SSOT：`docs/plans/2026-03-13-agentic-architecture-design.md`；对外只暴露 `/v1/skills` 网关 |
| `pr-server` | **私有** | Go 实现课程检索 / README 读写 / PR 提交 |

**HIT-A 已在用、且直接依赖 HOA 数据的 skill**（`all_api/agent-backend-api/v1.md`）：

| Skill | 输入 | 现状依赖 |
| --- | --- | --- |
| `courses.search` | `keyword` / `campus` / `limit` | 匹配 `code/name/repo/teachers/aliases`，返回 `teachers[]`、`aliases[]` |
| `course.read` | `campus` / `course_code` / `include_toml` | README-first：`readme_md` 默认返回，`include_toml=true` 才带 `readme_toml` |
| `hit.teacher` / `hit.teachers` | `name` / `pinyin` / `department` | 走 `crawl4ai` 爬 `homepage.hit.edu.cn`，非 HOA 数据 |

**迁移含义**：`courses.search` 和 `course.read` 换成指向 HOA 官方 API 即可，下游（HITA App、AstrBot 插件、bot-backend）**零改动**。

---

## 3. 目标架构

```
                       ┌───────────────────────────────────────────┐
   第三方 Agent        │        HITSZ-OpenAuto 官方接口层           │
  (Claude Code /       │                                           │
   Cursor / HITA App / │  https://hoa.moe/api/v1   REST + OpenAPI   │
   AstrBot / 自研)  ──▶│  https://hoa.moe/api/mcp   MCP (HTTP)      │
                       │        ┌──────────────────────┐            │
                       │        │  hoa-fuma (Next.js)   │            │
                       │        │  ├─ /api/v1/*  路由    │            │
                       │        │  └─ /api/mcp   路由    │            │
                       │        └───────────┬──────────┘            │
                       │                    │ 读                    │
                       │      ┌─────────────┼─────────────┐        │
                       │      ▼             ▼             ▼        │
                       │  content/docs/  lib/data/   readme.toml    │
                       │  (hoa-backend  (major-data) (课程仓 ×155)  │
                       │   生成快照)                                   │
                       └───────────────────────────────────────────┘
                                          │
                       写入路径(v2) ───────┴──▶ GitHub App / PAT → fork+PR
```

**核心原则**

1. **归属正确**：接口由 HITSZ-OpenAuto 拥有，路径与文档都在该组织内，HIT-A 变为消费方。
2. **只读优先**：v1 全部 GET、零鉴权、零副作用。写入路径 v2 再说（见 §7 路线图）。
3. **快照 + 增量**：读走构建期快照（`content/docs` + `lib/data`，每日 cron 重建），保证低延迟与稳定；高频变动项（资料文件列表）走 GitHub API + ETag。
4. **不重复造轮子**：复用现有 `lib/search-index.ts`、`lib/docs-tree.ts`、`lib/course-frontmatter.ts`、`lib/github.ts`，不新写索引。
5. **契约即代码**：OpenAPI 与 MCP 工具 schema 进仓库、进 CI 校验，改接口必须改 spec。

---

## 4. REST API v1 契约

Base URL：`https://hoa.moe/api/v1`（同域，站点已有部署与 CI/CD）

| Method & Path | 说明 | 鉴权 |
| --- | --- | --- |
| `GET /courses` | 课程检索/筛选（`q` `major` `year` `semester` `teacher` `limit` `cursor`） | 公开 |
| `GET /courses/{code}` | 课程完整结构化信息（描述、章节、教师、成绩构成、学时学分、资料树） | 公开 |
| `GET /courses/{code}/readme?format=md\|toml` | 原始 README 文本（对齐 HIT-A `course.read` 的 README-first 语义） | 公开 |
| `GET /courses/{code}/materials?path=` | 资料文件树（节点类型、大小、更新时间、下载地址） | 公开 |
| `GET /teachers?q=&course=` | 教师索引（含其课程列表、评价数） | 公开 |
| `GET /grades` / `GET /grades/{code}` | 成绩构成（`grades_summary.json` 118 门 + 课程 frontmatter） | 公开 |
| `GET /plans/{year}/{major}` | 培养方案课程列表 | 公开 |
| `GET /search?q=` | 全站检索（复用现有索引；课程 / 博客 / 新闻） | 公开 |
| `GET /meta` | API 版本、数据快照时间、数据 commit、课程总数 | 公开 |
| `GET /openapi.json` | OpenAPI 3.1 文档 | 公开 |

**通用约定**

- 错误统一为 `{ "error": { "code": "NOT_FOUND", "message": "...", "details": {...} } }`
- 响应头：`X-HOA-API-Version: v1`、`X-HOA-Data-Generated-At`、`X-HOA-Data-Commit`、`ETag`
- 缓存：`Cache-Control: public, max-age=300, stale-while-revalidate=86400`
- CORS：GET 允许 `*`（任何 Web Agent 都能直接调）；`ETag`/`If-None-Match` → 304
- 限流：按 IP 令牌桶 60 req/min，超限 429 + `Retry-After`；持 API Key 可提额
- 稳定 ID：课程标识统一用**大写课程代码**（如 `AUTO3005`），绝不暴露内部 slug / 目录结构
- 稳定字段：`code` `name` `aliases[]` `teachers[]` `repo` `url` `site_url` `updated_at`

完整机器可读契约见 [`docs/openapi.yaml`](./openapi.yaml)。

---

## 5. MCP Server 契约

- 端点：`https://hoa.moe/api/mcp`
- 传输：**Streamable HTTP（无状态模式）**——每个请求独立处理，不依赖 session，天然适配 CDN / 多副本 / Serverless
- 协议版本：遵循 MCP 规范 `initialize` / `tools/list` / `tools/call` / `resources/list` / `resources/read` / `prompts/list` / `ping`
- 认证：v1 无需鉴权；v2 写工具用 `Authorization: Bearer hoa_xxx`

### 5.1 工具（Tools）

| 工具 | 作用 | 关键入参 |
| --- | --- | --- |
| `search_courses` | 按关键词/专业/年级/教师检索课程 | `q` `major` `year` `semester` `teacher` `limit` |
| `get_course` | 取课程完整结构化信息 | `code` `include[]`（`sections`/`lecturers`/`grading`/`materials`/`summary`） |
| `get_course_readme` | 取原始 README | `code` `format`(`md`\|`toml`) |
| `get_course_materials` | 取资料文件树/单个文件信息 | `code` `path` `limit` |
| `list_teachers` | 查教师及其课程 | `q` `course` |
| `get_grading` | 查成绩构成 | `code` |
| `get_curriculum_plan` | 查培养方案 | `year` `major` |
| `search_site` | 全站检索（课程+博客+新闻） | `q` `limit` |

### 5.2 资源（Resources）

| URI | 内容 |
| --- | --- |
| `hoa://course/{code}` | 课程 JSON |
| `hoa://course/{code}/readme` | README 文本 |
| `hoa://teacher/{name}` | 教师 JSON |
| `hoa://plan/{year}/{major}` | 培养方案 JSON |

### 5.3 与 HIT-A skill 的对应关系

| HIT-A skill | HOA MCP 工具 | REST 端点 |
| --- | --- | --- |
| `courses.search` | `search_courses` | `GET /api/v1/courses` |
| `course.read` | `get_course_readme` | `GET /api/v1/courses/{code}/readme` |
| `hit.teachers` | `list_teachers` | `GET /api/v1/teachers` |
| `hit.teacher` | — | 仍属 HIT-A 自有数据（教师主页爬取），不归 HOA |

---

## 6. 鉴权、限流与安全

| 面 | 策略 |
| --- | --- |
| 读接口 | 完全公开、无鉴权 |
| 写接口（v2） | `Authorization: Bearer hoa_xxx`，scope：`courses:write` / `materials:write` / `pr:create` |
| 写身份 | 优先 **GitHub App installation token**（组织级、可审计、可吊销）；过渡期接受用户 PAT（仅需对**自己 fork** 的写权限） |
| 限流 | 匿名 60 req/min；持 Key 600 req/min；429 + `Retry-After` |
| 滥用防护 | 资料文件走 GitHub Contents API 代理或直链 raw，**不代理大文件**（设体积上限，如 >20MB 只回元数据 + raw 链接） |
| 隐私 | 只暴露公开仓内容；`author` 字段若课程仓中为 GitHub 用户名，视为已公开信息，但提供 `?redact_authors=1` 可选脱敏 |
| CORS | 只读接口 `Access-Control-Allow-Origin: *`；写接口不开放跨域 |

---

## 7. 实施路线图

| 阶段 | 内容 | 产出 | 预估 |
| --- | --- | --- | --- |
| **P0 契约** | 本文档 + `api/openapi.yaml` + MCP 工具 schema；评审并冻结 v1 字段 | 契约仓库 | 2 天 |
| **P1 只读 API** | `hoa-fuma` 新增 `/api/v1/*` 路由，复用 `lib/search-index.ts`、`lib/docs-tree.ts`、`lib/github.ts`、`lib/data/*`；接入 OpenAPI 与限流 | 可用 REST API | 3–5 天 |
| **P2 MCP** | 新增 `/api/mcp` Streamable HTTP 路由（`@modelcontextprotocol/sdk`，无状态）；工具/资源按 §5 实现 | 可用 MCP Server | 2–3 天 |
| **P3 官网文档** | 官网新增 `/docs/api` 页面（Quickstart、鉴权、示例），`llms.txt` 增加 API 入口；`hoa-skills` 增加 `hoa-query` 技能（读数据） | 对外可发现 | 2 天 |
| **P4 HIT-A 对接** | `agent-backend` 的 `courses.search` / `course.read` 改为转发 HOA 官方 API（保持 `ok/output` 包装，下游零改动）；HITA App / AstrBot 插件切流 | HIT-A 去重 | 3–5 天 |
| **P5 写能力** | GitHub App 鉴权、`POST /api/v1/contributions`（结构化 TOML ops → fork+PR）、审计与配额 | 可写入 | 1–2 周 |

**P4 的收益**：HIT-A 的 `pr-server` 里「读 HOA 数据」的部分可以删掉，只留「写 PR」的部分；两边职责彻底清晰。

---

## 8. 落地形态：独立服务 `hoa-api`

**决策：独立仓库 + 独立部署**，而不是把路由塞进 `hoa-fuma` 站点。

| 考量 | 独立服务 `hoa-api` | 站点内 `/api/v1` |
| --- | --- | --- |
| 数据可控 | SQLite 索引 + 自有同步节奏，与站点构建解耦 | 只能读站点构建产物，实时性差 |
| 写入路径 | 可承载 GitHub App 鉴权、PR 编排、审计 | 站点是只读渲染，改造代价高 |
| 版本演进 | 独立 SemVer，OpenAPI 契约进仓库做 CI 漂移校验 | 与站点发布节奏耦合 |
| 运维 | 独立 systemd 服务 + 独立 nginx vhost | 与站点共享进程与故障域 |
| 归属 | 仓库在 HITSZ-OpenAuto 组织下，契约公开可 review | 同左 |

**最终形态**

- 仓库：[`HITSZ-OpenAuto/hoa-api`](https://github.com/HITSZ-OpenAuto/hoa-api)（公开）
- 技术栈：Python 3.11 + FastAPI（REST）+ MCP SDK（Streamable HTTP）+ SQLite
- 部署：TXYun-1（139.199.173.108）`:8099`，systemd 托管，nginx 反代
- 端点：`https://<host>/api/v1` 与 `https://<host>/mcp`
- 兼容层：`/v1/courses:search`、`/v1/course:read` 逐字节复刻 `course-server` 响应信封，
  HIT-A 只需改一行环境变量 `COURSE_SERVER_URL` 即可切流

站点 `hoa-fuma` 侧保留 `/api/search` 与 `llms.txt`，并新增指向官方 API 的文档页与 MCP 配置片段，
两者互补而非重复。

---

## 9. 风险与对策

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| 155 个仓的 `readme.toml` 历史 schema 不统一 | 解析失败、字段缺失 | 复用 `repos-management/scripts/readme_to_toml.py` 的容错解析逻辑；API 只暴露**规范化后**的字段，异常仓进 `meta` 的健康度指标 |
| `README.md` 与 `readme.toml` 不同步 | 下游读到旧内容 | API 只以 TOML 为准；`README.md` 仅作 `format=md` 的展示副本，并带 `source_commit` 标识 |
| 课程代码与仓库 ID 不一致 | 查不到课程 | `lookup_table.toml` 提供教务码→仓库 ID 映射；API 同时接受课程代码与仓库 ID，内部归一 |
| 资料文件体积大（实测单仓 PDF 可达 35MB） | 带宽与超时 | 只回元数据 + GitHub raw 直链，不代理文件内容；单文件 >20MB 不做内容回源 |
| GitHub API 限流 | 资料列表不稳定 | 匿名 60/h 的配额下必须用 `GITHUB_TOKEN`（站点 `.env.example` 已有该变量）；列表走 ETag 缓存 5 分钟 |
| MCP 无状态与 CDN 缓存冲突 | SSE 长连接被缓存 | `Cache-Control: no-store` + `X-Accel-Buffering: no`；`initialize` 也必须无状态成功 |
| 第三方误用导致批量抓取 | 站点负载 | 限流 + 明确 ToS：鼓励走 API 而非爬站；`.well-known` 里给出建议轮询间隔 |

---

## 10. 下一步

1. ~~冻结 v1 契约~~ ✅ 本文件 §4/§5 + [`docs/openapi.yaml`](./openapi.yaml)
2. ~~确认落地形态~~ ✅ 独立服务 `hoa-api`（§8）
3. ~~实现 API 路由与 MCP 服务端~~ ✅ 见 `HITSZ-OpenAuto/hoa-api`
4. 部署到 TXYun-1 并端到端验证
5. HIT-A 切流：改 `COURSE_SERVER_URL` 一行即可
6. 写入路径（v2）：GitHub App 鉴权 + 结构化 ops → fork+PR

```jsonc
// MCP 客户端配置示例
{
  "mcpServers": {
    "hoa": { "type": "http", "url": "https://<host>/mcp" }
  }
}
```
