# REST API 与 MCP 参考

基址：`https://<host>/api/v1`　·　MCP：`https://<host>/mcp`

## 快速开始

```bash
# 检索课程
curl -s 'https://<host>/api/v1/courses?q=自动控制&limit=3'

# 课程详情
curl -s https://<host>/api/v1/courses/AUTO3005

# 教师反查课程
curl -s 'https://<host>/api/v1/courses?teacher=楼云江'

# Swagger UI
open https://<host>/api/v1/docs
```

## 约定

| 项 | 规则 |
| --- | --- |
| 认证 | v1 读接口公开，无需 token |
| 限流 | 60 次/分钟/IP，超限 `429` + `Retry-After` |
| 缓存 | `Cache-Control: public, max-age=300, stale-while-revalidate=86400`，支持 `ETag` / `If-None-Match` → `304` |
| CORS | 读接口 `Access-Control-Allow-Origin: *` |
| 版本 | 响应头 `X-HOA-API-Version: v1`；快照时间 `X-HOA-Data-Generated-At` |
| 错误 | `{"error": {"code": "...", "message": "...", "details": {}}}` |
| 课程标识 | **仓库 ID**（如 `AUTO3005`），同时接受 `readme.toml` 里的 `course_code` 与教务别名 |

> 课程标识以仓库 ID 为准是刻意的：历史课程仓的 `course_code` 字段并不总等于仓库名
> （例如 `MATH1005K` 仓里写的是 `MATH1005`），以它作主键会互相覆盖。

## 端点

### 课程

#### `GET /api/v1/courses`

| 参数 | 说明 |
| --- | --- |
| `q` | 关键词：课程代码 / 名称 / 别名 / 教师 / 描述 |
| `teacher` | 教师姓名（精确或包含匹配） |
| `major` / `year` | 专业 / 年级过滤 |
| `limit` | 默认 20，上限 100 |

```json
{
  "items": [
    {
      "code": "AUTO3005",
      "course_code": "AUTO3005",
      "name": "机器人学导论",
      "aliases": ["AUTO3005"],
      "teachers": ["楼云江", "杜惠"],
      "repo": "AUTO3005",
      "url": "https://github.com/HITSZ-OpenAuto/AUTO3005",
      "site_url": "https://hoa.moe/docs/2024/080717T/junior-spring/AUTO3005",
      "credit": 3.0,
      "updated_at": "2026-10-14T02:11:00Z"
    }
  ],
  "total": 1
}
```

#### `GET /api/v1/courses/{code}`

返回课程完整信息。用 `include` 控制字段（默认 `sections,lecturers,grading`）：
`summary,sections,lecturers,grading,materials`。

```json
{
  "code": "AUTO3005",
  "name": "机器人学导论",
  "description": "本课程主要采用基于旋量理论……",
  "lecturers": {
    "intro": [{"content": "教师团队总体介绍", "author": {"name": "管理员", "date": "2025-01"}}],
    "items": [{"name": "楼云江", "reviews": [{"content": "会细致推导公式……", "author": {"name": "昵称", "date": "2025-03"}}]}],
    "summary": [{"content": "建议尽早选课", "author": null}]
  },
  "sections": [{"title": "教材与在线资源", "items": [{"content": "- 教材: …", "author": null}]}],
  "grading": {
    "variants": {"default": [{"name": "作业", "percent": "15%"}]},
    "items": [{"name": "作业", "percent": "15%"}]
  },
  "source": {"repo": "AUTO3005", "commit": "…", "updated_at": "…", "synced_at": "…"}
}
```

#### `GET /api/v1/courses/{code}/readme?format=md|toml`

返回原文。`md` 是渲染后的 `README.md`，`toml` 是事实来源 `readme.toml`（README-first 语义，同 HIT-A `course.read`）。

#### `GET /api/v1/courses/{code}/materials?path=&limit=`

资料文件树。只回元数据与下载地址，**不代理文件内容**。

```json
{
  "code": "AUTO3005",
  "path": "",
  "nodes": [
    {"name": "exams", "type": "folder", "path": "exams", "size": null, "url": null},
    {"name": "2025.pdf", "type": "file", "path": "exams/2025.pdf", "size": 1048576,
     "url": "https://raw.githubusercontent.com/HITSZ-OpenAuto/AUTO3005/main/exams/2025.pdf"}
  ],
  "total": 2
}
```

### 教师

#### `GET /api/v1/teachers?q=&course=&limit=`

```json
{"items": [{"name": "楼云江", "courses": ["AUTO3005", "AUTO1001"], "review_count": 3}], "total": 1}
```

### 成绩

#### `GET /api/v1/grades` · `GET /api/v1/grades/{code}`

数据源 `hoa-major-data/grades_summary.json`，含按年份的变体：

```json
{
  "code": "AUTO3005",
  "variants": {"default": [{"name": "作业", "percent": "15%"}], "2021_default": []},
  "items": [{"name": "作业", "percent": "15%"}]
}
```

### 培养方案

#### `GET /api/v1/plans` · `GET /api/v1/plans/{year}/{major}`

`major` 支持专业名称（`自动化`）或专业代码。

### 检索与元信息

- `GET /api/v1/search?q=&type=&limit=` —— 课程 + 教师统一检索
- `GET /api/v1/meta` —— 版本、快照时间、课程数、教师数、MCP 端点

---

## MCP

端点 `https://<host>/mcp`，Streamable HTTP（无状态模式）。

```json
{
  "mcpServers": {
    "hoa": { "type": "http", "url": "https://<host>/mcp" }
  }
}
```

### 工具

| 工具 | 入参 | 返回 |
| --- | --- | --- |
| `search_courses` | `q`, `teacher`, `limit` | 课程列表 |
| `get_course` | `code`, `include` | 课程完整信息 |
| `get_course_readme` | `code`, `format` | README 原文 |
| `get_course_materials` | `code`, `path`, `limit` | 资料文件树 |
| `list_teachers` | `q`, `course` | 教师列表 |
| `get_grading` | `code` | 成绩构成 |
| `get_curriculum_plan` | `year`, `major` | 培养方案 |
| `search_site` | `q`, `limit` | 统一检索结果 |

### 资源

| URI | 内容 |
| --- | --- |
| `hoa://course/{code}` | 课程 JSON |
| `hoa://course/{code}/readme` | README 文本 |
| `hoa://teacher/{name}` | 教师 JSON |
| `hoa://plan/{year}/{major}` | 培养方案 JSON |

### 手工调用示例

```bash
curl -s -X POST https://<host>/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
        "name":"search_courses",
        "arguments":{"q":"自动控制","limit":3}}}'
```

---

## 兼容层

为 HIT-A `course-server` 保留的 POST 接口，响应信封逐字节一致，切换时下游零改动：

- `POST /v1/courses:search` —— `{"keyword": "...", "limit": 10}`
- `POST /v1/course:read` —— `{"target": {"campus": "shenzhen", "course_code": "..."}, "include_toml": false}`

详见 [`MIGRATION-HIT-A.md`](./MIGRATION-HIT-A.md)。
