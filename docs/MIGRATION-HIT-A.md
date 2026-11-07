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

两者信封一致（`{ok, data:{results:[...]}}`），`hoa-api` 额外保证 `teachers`/`aliases` 非空。
**注意老服务忽略 `limit`**，因此对比时不要按条数判断，要按课程代码集合判断。

课程清单以 `repos_list.txt` 为准，老服务按组织全量仓库建索引，
所以老服务可能多出已删除的仓（例如 `SOPR`）——这是新服务更准，不是回归。

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

> 切到官方域名时把这一行改成 `COURSE_SERVER_URL=https://api.hoa.moe`，
> 并注意老服务对上游不做鉴权，官方 API 的公开只读接口同样不需要 token。

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

## 4. 行为差异（已逐项实测对齐）

| 差异点 | course-server | hoa-api | 影响 |
| --- | --- | --- | --- |
| 传输方法 | POST | POST（兼容层） | 无 |
| 数据新鲜度 | 实时读 GitHub（受 GitHub API 配额与延迟影响） | SQLite 快照，默认 6 小时同步一次 | 刚上传的资料最多滞后一个同步周期 |
| 失败语义 | 网关超时 / GitHub 错误 | 统一 `{ok:false, error:{code,message}}` | 错误信息更规范 |
| 跨校区 | 支持 shenzhen / harbin / weihai | **覆盖三校区**（见下） | 无 |
| 检索字段 | 代码 / 名称 / 仓库 / 教师 / **子课程别名** + **昵称表** + GitHub 代码兜底 | 同上（本地等价实现） | 无 |
| `limit` 参数 | **被忽略**（最多返回 200 条） | 兼容层同样忽略 | 无 |
| 课程清单 | 组织的全部仓库 | 以 `repos_list.txt` 为准 | 已删除的仓不再出现（见下） |
| 限流 | 旧服务只在 localhost 提供服务，**不限流** | 公开 API 按 IP 限流；**兼容层 `/v1/*` 阈值放宽到 10 倍**（默认 1200/min） | 正常 agent 流量不会触发；若真遇到 429，调 `HOA_COMPAT_RATE_LIMIT_PER_MIN` |

### 4.0 一致性检查脚本

兼容层"不许漂移"需要有可复现的验证手段：

```bash
# 在能同时访问新旧服务的地方（例如部署了兜底服务的机器）
python scripts/compare_compat.py --old http://localhost:8081 --new http://localhost:8099
```

脚本用 HIT-A 的真实报文格式打两个服务，比对检索结果的课程代码集合与 `course:read` 的响应结构。
当前基线（147 个查询 × 3 个 campus）：**检索覆盖 138/147，缺口全部是 `SOPR`**（已删除的仓），
`course:read` 结构 9/9 一致。

### 4.1 跨校区不是缺口

老服务的 `internal/localcache/cache.go` 里写得很清楚：

```go
// HOA 实体数据只在深圳 org；本部/威海在 Search/Resolve 层别名过来。
if c.Campus != config.CampusShenzhen {
    fmt.Printf("cache: skip campus %s (alias to shenzhen HOA)\n", c.Campus)
    continue
}
```

即 harbin / weihai 并不是独立课表，只是深圳 HOA 数据的别名视图。实测 `campus=shenzhen / harbin / weihai`
三种取值在新旧两侧返回完全一致的结果集。

### 4.2 检索语义的三处补齐

老服务的匹配规则已按源码逐条复刻：

| 规则 | 老实现 | 新实现 |
| --- | --- | --- |
| 子课程别名 | `parseSummary` 把 `[[courses]]` 的 `name`/`code` 收进 `Aliases` | `parse_course_toml` 同样提取；多课程仓（如 EE30XX 的「电气传动自动控制系统 / EE3004」）可被搜到 |
| 昵称表 | `nicknames.json`：`线性代数→代数`、`高数→微积分`… | `src/hoa_api/nicknames.py`，与老表逐条一致 |
| 正文兜底 | 缓存未命中时回落 GitHub code search | 本地匹配已同步的 `readme.toml` / `readme.md`，不消耗 GitHub 配额 |

另外老服务**忽略请求里的 `limit`**（`cacheLimit` 固定 200），兼容层保持同样语义，
避免 HIT-A 传 `limit=10` 时看到的课程条数变少。

### 4.3 覆盖对拍结果

用 HIT-A 的真实报文格式（`keyword` + `campus` + `target.course_code` + `include_toml`）对拍 51 个查询：

- **46 个查询**：新服务结果完全覆盖老服务；
- **3 个查询**：老服务多出 `SOPR`——该仓在 `HITSZ-OpenAuto` 已 **404 不存在**，是老服务本地缓存里的僵尸条目，新服务按 `repos_list.txt` 正确排除；
- **2 个查询**：老服务自身报错（`化学` / `通信`）。

结论：**新服务是老服务的严格超集**（在老服务能给出真实数据的前提下）。

### 4.4 HIT-A 实际只用两个读端点

`agent-backend` 只引用 `/v1/courses:search` 与 `/v1/course:read`
（`internal/courseclient/courseclient.go:43,52`、`internal/skills/course_skills.go:64,127`），
响应体是 `json.RawMessage` 原样透传给下游，**不解析成结构体**，因此新增字段不影响它。
写入类端点（`course:preview` / `course:submit` / `pr:lookup`）与本次切流无关，继续留在旧服务。

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
