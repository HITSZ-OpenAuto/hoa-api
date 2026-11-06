#!/usr/bin/env python3
"""校验工作流里内嵌的 Python 片段。

YAML 块标量会剥掉公共缩进，内嵌的 `python3 -c '...'` 片段如果依赖缩进，
剥离后就会变成 `IndentationError: unexpected indent`——这类问题在
GitHub Actions 上才会暴露，代价是一次失败部署。这里在提交前静态检查。

注意：必须先按 YAML 解析拿到脚本的真实内容（缩进已被剥掉），
直接读文件原文会误报。

用法：
    python3 scripts/check_workflow_python.py .github/workflows/deploy.yml
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

# 匹配 python3 -c '...' 片段（单引号包裹，跨行）
INLINE_PY = re.compile(r"python3\s+-c\s+'(.*?)'", re.DOTALL)
# 匹配 python3 - <<'EOF' ... EOF 片段（heredoc 行尾可能带重定向）
HEREDOC_PY = re.compile(r"python3\s+-\s*<<'(\w+)'[^\n]*\n(.*?)\n\1", re.DOTALL)


def _scripts_from_yaml(text: str) -> list[tuple[str, str]]:
    """返回 [(定位描述, 脚本内容)]，脚本内容已按 YAML 语义剥离缩进。"""
    doc = yaml.safe_load(text)
    found: list[tuple[str, str]] = []

    def walk(node: object, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif isinstance(node, str) and ("python3" in node):
            found.append((path, node))

    walk(doc, "root")
    return found


def check_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []

    for where, script in _scripts_from_yaml(text):
        for match in INLINE_PY.finditer(script):
            snippet = match.group(1)
            body = "\n".join(line for line in snippet.splitlines() if line.strip())
            if not body:
                continue
            try:
                compile(body, f"{path}:{where}", "exec")
            except SyntaxError as exc:
                problems.append(f"{path} [{where}] 内嵌 python 片段语法错误：{exc}")

        for match in HEREDOC_PY.finditer(script):
            snippet = match.group(2)
            try:
                compile(snippet, f"{path}:{where}", "exec")
            except SyntaxError as exc:
                problems.append(f"{path} [{where}] heredoc python 片段语法错误：{exc}")

    return problems


def main(argv: list[str]) -> int:
    paths = [Path(p) for p in argv[1:]]
    if not paths:
        paths = sorted(Path(".github/workflows").glob("*.yml"))
    problems: list[str] = []
    for path in paths:
        problems.extend(check_file(path))
    if problems:
        for item in problems:
            print(f"✗ {item}")
        return 1
    print(f"✓ {len(paths)} 个工作流的内嵌 Python 片段检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
