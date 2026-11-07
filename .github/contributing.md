# Contributing Guide

本仓库是 **HITSZ-OpenAuto 官方 API 与 MCP Server** 的实现（REST API + MCP Server），
服务 HITSZ 课程数据，供 HIT-A 的 agent 及任何第三方 Agent 消费。

## Code

- Please kindly open an issue first to discuss with the maintainers.
- Keep your scope of changes as isolated as possible
- Pass the pre-commit.

### 本仓库特有的约定

- **课程身份以仓库 ID 为准**。课程仓 `readme.toml` 里的 `course_code` 可能与仓库名不一致
  （例如 `MATH1005K` 仓里写的是 `MATH1005`），也可能是未填写的模板值
  （`course_code = "CODE1234"`）。它只作为**别名**参与检索，不能当主键。
- **课程仓清单以 `HITSZ-OpenAuto/repos-management` 的 `repos_list.txt` 为准**，
  不要用仓库描述前缀之类的启发式规则去过滤课程。
- **`/v1` 兼容层必须保持与旧 `course-server` 的响应信封一致**。HIT-A 的
  `agent-backend` 会原样透传该响应，因此字段语义、检索层级（代码 / 名称 / 别名 / 教师 /
  昵称表 / 正文兜底）以及「忽略 `limit`」的行为都不能随意改动。
  改动前请先跑一遍新旧对拍。
- **REST 与 MCP 都要同步更新**。新增查询能力时，`api.py` 与 `mcp_server.py` 都要提供入口，
  并在 `docs/openapi.yaml` 里体现（CI 会校验契约未漂移）。

### 本地校验

```bash
pip install -e ".[dev]"
ruff check src tests scripts
pytest -q
python scripts/export_openapi.py          # 改动接口后需提交 docs/openapi.yaml
python scripts/check_workflow_python.py   # 工作流内嵌脚本的缩进陷阱检查
```

## Documentation

- 接口参考见 [`docs/API.md`](docs/API.md)
- 部署说明见 [`docs/DEPLOY.md`](docs/DEPLOY.md)
- 设计取舍见 [`docs/DESIGN.md`](docs/DESIGN.md)
- HIT-A 迁移说明见 [`docs/MIGRATION-HIT-A.md`](docs/MIGRATION-HIT-A.md)

## 部署

本仓库不直接持有任何凭据。部署由
[`HITSZ-OpenAuto/hoa-fuma`](https://github.com/HITSZ-OpenAuto/hoa-fuma) 的
`deploy-hoa-api.yml` 调用本仓库的 `.github/workflows/deploy.yml` 完成，
凭据（VPS SSH 密钥、Tailscale、Cloudflare）保存在 hoa-fuma 仓库的 secret 中。

- 推 main 本身**不会**触发部署；部署由 hoa-fuma 的工作流触发（手动 / 每日定时）。
- 改动本仓库后，如需立即上线，请在 hoa-fuma 触发 `Deploy HOA API` 工作流。
