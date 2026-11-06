"""数据同步管线：GitHub → SQLite。

同步策略：
- 课程仓清单来自 `repos-management/repos_list.txt`，再与组织仓库列表求交集，
  只保留描述以 ``HITSZ `` 开头的真课程仓。
- ``readme.toml`` / ``README.md`` 走 raw.githubusercontent（无 API 配额）。
- 目录树与 commit 走 api.github.com（带 ETag 条件请求，304 不计配额）。
- 培养方案与成绩构成从 `hoa-major-data` 的 tarball 一次取回。
"""

from __future__ import annotations

import io
import tarfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .config import Config
from .course_data import (
    parse_course_toml,
    parse_grading_payload,
    parse_plan_toml,
    teacher_review_counts,
)
from .db import Store
from .github import GitHubClient

REPO_LIST_URL = (
    "https://raw.githubusercontent.com/HITSZ-OpenAuto/repos-management/refs/heads/main/repos_list.txt"
)
MAJOR_DATA_TARBALL = "https://github.com/HITSZ-OpenAuto/hoa-major-data/archive/refs/heads/main.tar.gz"

MATERIAL_DIRS = ("assignments", "exams", "labs", "notes", "slides", "textbooks", "resources")
SKIP_TOP = {"README.md", "readme.toml", "LICENSE", ".github", ".git", ".gitignore"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class SyncReport:
    """一次同步的结果统计。"""

    started_at: str = field(default_factory=now_iso)
    finished_at: str = ""
    courses_total: int = 0
    courses_updated: int = 0
    courses_unchanged: int = 0
    courses_failed: int = 0
    materials: int = 0
    grades: int = 0
    plans: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "courses_total": self.courses_total,
            "courses_updated": self.courses_updated,
            "courses_unchanged": self.courses_unchanged,
            "courses_failed": self.courses_failed,
            "materials": self.materials,
            "grades": self.grades,
            "plans": self.plans,
            "errors": self.errors[:20],
        }


class SyncPipeline:
    """负责把 GitHub 上的 HOA 数据同步进本地 SQLite。"""

    def __init__(self, store: Store, config: Config) -> None:
        self.store = store
        self.config = config
        self.client = GitHubClient(token=config.github_token, user_agent=config.user_agent)

    def close(self) -> None:
        self.client.close()

    # ---------- 主流程 ----------

    def run(self, limit: int | None = None, include_major_data: bool = True) -> SyncReport:
        report = SyncReport()
        repos = self._list_course_repos()
        report.courses_total = len(repos)
        if limit:
            repos = repos[:limit]

        for repo_info in repos:
            repo = repo_info["repo"]
            try:
                if self._sync_repo(repo, repo_info):
                    report.courses_updated += 1
                else:
                    report.courses_unchanged += 1
            except Exception as exc:  # 单仓失败不影响整体
                report.courses_failed += 1
                report.errors.append(f"{repo}: {exc}")
                self.store.set_repo_sync(repo, status="error", error=str(exc)[:500])
            self.store.commit()

        if include_major_data:
            try:
                self._sync_major_data(report)
            except Exception as exc:
                report.errors.append(f"major-data: {exc}")

        report.materials = self.store.count_materials()
        report.finished_at = now_iso()
        self.store.set_meta("last_sync_at", report.finished_at)
        self.store.set_meta("last_sync_report", str(report.as_dict()))
        self.store.commit()
        return report

    # ---------- 仓库清单 ----------

    def _list_course_repos(self) -> list[dict[str, Any]]:
        """返回课程仓元信息 [{repo, branch, description, pushed_at}]。"""
        repo_list = self._fetch_repo_list()
        meta = self._fetch_org_repos()
        courses = []
        for repo in repo_list:
            info = meta.get(repo)
            if not info:
                continue
            description = info.get("description") or ""
            if not description.startswith("HITSZ "):
                continue
            courses.append(
                {
                    "repo": repo,
                    "branch": info.get("default_branch") or "main",
                    "description": description[len("HITSZ ") :].strip(),
                    "pushed_at": info.get("pushed_at"),
                }
            )
        courses.sort(key=lambda item: item["repo"])
        return courses

    def _fetch_repo_list(self) -> list[str]:
        result = self.client.get_text(REPO_LIST_URL)
        if not result.content:
            return []
        return [line.strip() for line in result.content.splitlines() if line.strip()]

    def _fetch_org_repos(self) -> dict[str, dict[str, Any]]:
        """分页拉取组织下所有仓库的元信息。"""
        meta: dict[str, dict[str, Any]] = {}
        for page in range(1, 6):
            url = self.client.api_url(
                f"/orgs/{self.config.org}/repos?per_page=100&page={page}"
            )
            result = self.client.get_json(url)
            if not result.ok or not isinstance(result.data, list):
                break
            if not result.data:
                break
            for item in result.data:
                if isinstance(item, dict) and item.get("name"):
                    meta[item["name"]] = item
            if len(result.data) < 100:
                break
        return meta

    # ---------- 单仓同步 ----------

    def _sync_repo(self, repo: str, info: dict[str, Any]) -> bool:
        """同步单个课程仓，返回是否发生更新。

        `info` 来自组织仓库列表，已含默认分支与 pushed_at，避免重复调用 API。
        """
        sync_row = self.store.get_repo_sync(repo)
        etag_toml = sync_row["etag_toml"] if sync_row else None
        etag_readme = sync_row["etag_readme"] if sync_row else None
        etag_tree = sync_row["etag_tree"] if sync_row else None

        branch = info.get("branch") or "main"
        toml_url = self.client.raw_url(self.config.org, repo, branch, "readme.toml")
        readme_url = self.client.raw_url(self.config.org, repo, branch, "README.md")

        toml_res = self.client.get_text(toml_url, etag_toml)
        readme_res = self.client.get_text(readme_url, etag_readme)

        tree_nodes: list[dict[str, Any]] = []
        tree_changed = False
        if self.config.sync_materials:
            tree_url = self.client.api_url(
                f"/repos/{self.config.org}/{repo}/git/trees/{branch}?recursive=1"
            )
            tree_res = self.client.get_json(tree_url, etag_tree)
            if tree_res.ok and isinstance(tree_res.data, dict):
                if tree_res.not_modified:
                    tree_nodes = self._load_materials_from_db(repo)
                else:
                    tree_nodes = self._materials_from_tree(tree_res.data, branch, repo)
                    tree_changed = True
                etag_tree = tree_res.etag

        readme_toml = toml_res.content or ""
        parsed = parse_course_toml(readme_toml)
        code = parsed["code"] or repo
        name = parsed["name"] or info.get("description") or repo

        unchanged = (
            toml_res.not_modified
            and readme_res.not_modified
            and not tree_changed
            and sync_row is not None
            and sync_row["status"] == "ok"
        )

        if not unchanged:
            self.store.upsert_course(
                {
                    "code": code,
                    "repo": repo,
                    "name": name,
                    "description": parsed["description"],
                    "repo_type": parsed["repo_type"],
                    "aliases": [],
                    "teachers": parsed["teachers"],
                    "sections": parsed["sections"],
                    "lecturers": parsed["lecturers"],
                    "grading": {},
                    "readme_md": readme_res.content or "",
                    "readme_toml": readme_toml,
                    "source_commit": self._head_commit(repo, branch),
                    "source_updated": info.get("pushed_at"),
                    "synced_at": now_iso(),
                    "materials": tree_nodes,
                }
            )
            if tree_nodes:
                self.store.replace_materials(code, tree_nodes)
            self.store.replace_teachers(code, teacher_review_counts(parsed["lecturers"]))

        self.store.set_repo_sync(
            repo,
            etag_toml=toml_res.etag if not toml_res.not_modified else None,
            etag_readme=readme_res.etag if not readme_res.not_modified else None,
            etag_tree=etag_tree,
            status="ok",
            error=None,
            synced_at=now_iso(),
        )
        return not unchanged

    def _head_commit(self, repo: str, branch: str) -> str | None:
        url = self.client.api_url(f"/repos/{self.config.org}/{repo}/commits/{branch}")
        result = self.client.get_json(url)
        if result.ok and isinstance(result.data, dict):
            return result.data.get("sha")
        return None

    # ---------- 资料目录 ----------

    def _materials_from_tree(
        self, tree: dict[str, Any], branch: str, repo: str
    ) -> list[dict[str, Any]]:
        """把 git tree 转成扁平的资料节点列表（含 parent）。"""
        entries = tree.get("tree") or []
        nodes: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path") or ""
            if not path or path.startswith("."):
                continue
            top = path.split("/", 1)[0]
            if top in SKIP_TOP and "/" not in path:
                continue
            if path.count("/") == 0 and path in SKIP_TOP:
                continue
            if top.startswith("."):
                continue

            is_dir = entry.get("type") == "tree"
            parent = path.rsplit("/", 1)[0] if "/" in path else ""
            node: dict[str, Any] = {
                "name": path.rsplit("/", 1)[-1],
                "type": "folder" if is_dir else "file",
                "path": path,
                "parent": parent,
                "size": entry.get("size"),
                "updated_at": None,
                "url": None,
            }
            if not is_dir:
                node["url"] = (
                    f"https://raw.githubusercontent.com/{self.config.org}/{repo}/{branch}/{path}"
                )
            nodes.append(node)
        return nodes

    def _load_materials_from_db(self, repo: str) -> list[dict[str, Any]]:
        course = self.store.get_course_by_repo(repo)
        if not course:
            return []
        return self.store.get_materials(course["code"])

    # ---------- major-data ----------

    def _sync_major_data(self, report: SyncReport) -> None:
        """一次性同步 grades / lookup_table / plans。"""
        result = self.client.get_bytes(MAJOR_DATA_TARBALL)
        if not result.content_bytes:
            raise RuntimeError("major-data tarball 下载失败")

        with tarfile.open(fileobj=io.BytesIO(result.content_bytes), mode="r:gz") as tar:
            members = {member.name: member for member in tar.getmembers()}

            grades_member = next(
                (m for name, m in members.items() if name.endswith("/grades_summary.json")),
                None,
            )
            if grades_member:
                payload = tar.extractfile(grades_member).read().decode("utf-8", "ignore")
                import json

                grades = json.loads(payload)
                for code, value in grades.items():
                    self.store.upsert_grade(code, parse_grading_payload(value))
                report.grades = len(grades)

            lookup_member = next(
                (m for name, m in members.items() if name.endswith("/lookup_table.toml")),
                None,
            )
            if lookup_member:
                text = tar.extractfile(lookup_member).read().decode("utf-8", "ignore")
                self._apply_lookup_table(text)

            if self.config.sync_plans:
                plan_members = [
                    m
                    for name, m in members.items()
                    if "/plans/" in name and m.name.endswith(".toml")
                ]
                for member in plan_members:
                    text = tar.extractfile(member).read().decode("utf-8", "ignore")
                    plan = parse_plan_toml(text)
                    if not plan["year"] or not plan["major"]:
                        continue
                    self.store.upsert_plan(
                        plan["year"], plan["major"], plan["major_code"], plan
                    )
                report.plans = len(plan_members)

        self.store.commit()

    def _apply_lookup_table(self, text: str) -> None:
        """把教务课程代码 → 仓库 ID 的映射写回课程的 aliases。"""
        from .course_data import loads_toml

        data = loads_toml(text)
        alias_map: dict[str, set[str]] = {}
        for course_code, mapping in data.items():
            if not isinstance(mapping, dict):
                continue
            for plan_id, repo_id in mapping.items():
                if isinstance(repo_id, str) and repo_id:
                    alias_map.setdefault(repo_id.upper(), set()).add(course_code.upper())

        for repo_id, aliases in alias_map.items():
            course = self.store.get_course_by_repo(repo_id)
            if not course:
                continue
            merged = sorted(set(course.get("aliases") or []) | aliases)
            self.store.upsert_course({**course, "aliases": merged, "synced_at": now_iso()})
