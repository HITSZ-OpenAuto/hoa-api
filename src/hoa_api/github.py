"""GitHub 访问层：支持 ETag 条件请求，避免重复消耗 API 配额。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

RETRY_STATUS = {429, 500, 502, 503, 504}


@dataclass
class FetchResult:
    """一次条件请求的结果。"""

    content: str | None = None
    data: Any = None
    content_bytes: bytes | None = None
    etag: str | None = None
    not_modified: bool = False
    status: int = 0

    @property
    def ok(self) -> bool:
        return self.status == 0 or 200 <= self.status < 300


class GitHubClient:
    """轻量 GitHub 客户端（只读）。

    部分中国大陆网络环境无法直连 ``raw.githubusercontent.com``（会超时），
    因此这里提供两条内容获取通道：raw 与 Contents API，
    由 :meth:`probe_raw` 探测后择优使用。
    """

    def __init__(
        self,
        token: str | None = None,
        user_agent: str = "hoa-api/1.0",
        timeout: float = 30.0,
        max_retries: int = 3,
        raw_timeout: float = 8.0,
    ) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": user_agent,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(headers=headers, timeout=timeout, follow_redirects=True)
        self._max_retries = max_retries
        # raw 通道在受限网络下可能挂起，给它更短的超时与更少的重试，
        # 以便尽快降级到可靠的 Contents API。
        self._raw = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=raw_timeout,
            follow_redirects=True,
        )
        self._raw_max_retries = 1
        self._raw_ok: bool | None = None

    def close(self) -> None:
        self._client.close()
        self._raw.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---------- 内部 ----------

    def _request(
        self,
        client: httpx.Client,
        url: str,
        etag: str | None,
        accept: str | None = None,
        binary: bool = False,
        max_retries: int | None = None,
    ) -> FetchResult:
        headers = {}
        if accept:
            headers["Accept"] = accept
        if etag:
            headers["If-None-Match"] = etag
        attempts = self._max_retries if max_retries is None else max_retries

        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                response = client.get(url, headers=headers)
            except httpx.HTTPError as exc:  # 网络抖动
                last_error = exc
                time.sleep(1.5 * (attempt + 1))
                continue

            if response.status_code == 304:
                return FetchResult(etag=etag, not_modified=True, status=304)
            if response.status_code == 404:
                return FetchResult(status=404)
            if response.status_code in RETRY_STATUS:
                time.sleep(1.5 * (attempt + 1))
                continue
            if response.status_code >= 400:
                return FetchResult(status=response.status_code)

            new_etag = response.headers.get("etag")
            if binary:
                return FetchResult(
                    content_bytes=response.content, etag=new_etag, status=response.status_code
                )
            return FetchResult(content=response.text, etag=new_etag, status=response.status_code)

        raise RuntimeError(f"请求失败: {url} ({last_error})")

    # ---------- 公开 ----------

    def get_text(self, url: str, etag: str | None = None) -> FetchResult:
        """取文本内容（raw.githubusercontent 或任意 URL）。"""
        return self._request(
            self._raw, url, etag, accept="text/plain, */*", max_retries=self._raw_max_retries
        )

    def get_bytes(self, url: str) -> FetchResult:
        """取二进制内容（如 tarball）。"""
        return self._request(self._raw, url, None, accept="*/*", binary=True)

    def get_json(self, url: str, etag: str | None = None) -> FetchResult:
        """取 JSON（api.github.com）。"""
        result = self._request(self._client, url, etag, accept="application/vnd.github+json")
        if result.content is None:
            return result
        import json

        try:
            result.data = json.loads(result.content)
        except ValueError:
            result.status = 500
        return result

    def raw_url(self, org: str, repo: str, ref: str, path: str) -> str:
        return f"https://raw.githubusercontent.com/{org}/{repo}/{ref}/{path}"

    def api_url(self, path: str) -> str:
        return f"https://api.github.com{path}"

    # ---------- 内容获取 ----------

    def probe_raw(self, timeout: float = 8.0) -> bool:
        """探测 raw.githubusercontent.com 是否可达，结果缓存。"""
        if self._raw_ok is not None:
            return self._raw_ok
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                response = client.get(
                    "https://raw.githubusercontent.com/HITSZ-OpenAuto/hoa-fuma/main/README.md"
                )
            self._raw_ok = response.status_code == 200
        except httpx.HTTPError:
            self._raw_ok = False
        return self._raw_ok

    def get_file_text(
        self, org: str, repo: str, ref: str, path: str, etag: str | None = None
    ) -> FetchResult:
        """取仓库内文件文本。

        raw.githubusercontent.com 在部分网络下不稳定，因此单文件失败时
        立即退回 Contents API，而不是让整轮同步卡住。
        """
        if self.probe_raw():
            try:
                result = self.get_text(self.raw_url(org, repo, ref, path), etag)
                if result.status != 0 and result.status != 404:
                    return result
                if result.status == 404:
                    return result
            except (RuntimeError, httpx.HTTPError):
                pass
        return self.get_contents(org, repo, path, ref, etag)

    def get_contents(
        self, org: str, repo: str, path: str, ref: str, etag: str | None = None
    ) -> FetchResult:
        """通过 Contents API 取文件内容（base64 解码）。"""
        import base64

        url = self.api_url(f"/repos/{org}/{repo}/contents/{path}?ref={ref}")
        result = self.get_json(url, etag)
        if not result.ok or not isinstance(result.data, dict):
            return result
        payload = result.data
        if payload.get("type") != "file" or "content" not in payload:
            result.status = 404
            return result
        try:
            raw = base64.b64decode(payload["content"].replace("\n", ""))
            result.content = raw.decode("utf-8", "replace")
        except (ValueError, TypeError) as exc:
            result.status = 500
            result.content = None
            result.error = str(exc)  # type: ignore[attr-defined]
        return result
