## 变更类型

- [ ] REST 接口（`/api/v1/*`）
- [ ] MCP 工具或资源（`/mcp`）
- [ ] 兼容层（`/v1/*`，影响 HIT-A 的 `course-server` 兼容）
- [ ] 数据同步 / 采集管线
- [ ] 部署与 CI
- [ ] 文档

## 变更内容

<!-- 说明改了什么，为什么这么改。 -->

## 影响面

- [ ] **兼容层语义未变**：`/v1` 的响应信封、检索层级与「忽略 `limit`」的行为保持与旧 `course-server` 一致
- [ ] 若改变了检索结果或字段语义，已附新旧对拍结果（至少 40 个常用查询）

  ```
  # 对拍示例
  python scripts/compare_compat.py   # 或在服务器上手工对拍
  ```

- [ ] `docs/openapi.yaml` 已重新导出并提交（CI 会校验契约未漂移）
- [ ] REST 与 MCP 两侧都已覆盖新增能力

## 本地校验

- [ ] `ruff check src tests scripts`
- [ ] `pytest -q`
- [ ] `python scripts/export_openapi.py`
- [ ] `python scripts/check_workflow_python.py`

## 关联

<!-- 关联 issue，例如 Closes #123 -->
