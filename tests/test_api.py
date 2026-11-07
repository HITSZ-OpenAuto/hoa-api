"""REST 路由与兼容层测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hoa_api.api import create_app
from hoa_api.config import Config
from hoa_api.db import Store
from hoa_api.service import Service


@pytest.fixture()
def client(tmp_path):
    config = Config(db_path=str(tmp_path / "test.db"), rate_limit_per_min=1000)
    store = Store(config.db_path)
    store.upsert_course(
        {
            "code": "AUTO3005",
            "repo": "AUTO3005",
            "name": "机器人学导论",
            "description": "旋量理论体系",
            "repo_type": "normal",
            "aliases": ["机器人学"],
            "teachers": ["楼云江"],
            "sections": [{"title": "教材", "items": [{"content": "书名", "author": None}]}],
            "lecturers": {"intro": [], "items": [{"name": "楼云江", "reviews": []}], "summary": []},
            "grading": {},
            "readme_md": "# AUTO3005\n\n机器人学导论",
            "readme_toml": 'course_name = "机器人学导论"',
            "source_commit": "abc",
            "source_updated": "2026-10-14T00:00:00Z",
            "synced_at": "2026-11-06T00:00:00Z",
            "materials": [],
        }
    )
    store.replace_materials(
        "AUTO3005",
        [{"name": "exams", "type": "folder", "path": "exams", "parent": ""}],
    )
    store.replace_teachers("AUTO3005", [("楼云江", 1)])
    store.upsert_grade("AUTO3005", {"variants": {"default": []}, "items": [{"name": "作业", "percent": "50%"}]})
    store.commit()
    app = create_app(config, store)
    with TestClient(app) as test_client:
        yield test_client
    store.close()


def test_meta(client):
    data = client.get("/api/v1/meta").json()
    assert data["api_version"] == "v1"
    assert data["course_count"] == 1
    assert data["teacher_count"] == 1


def test_meta_public_urls_follow_public_origin():
    """API 自身的对外地址应跟随 HOA_PUBLIC_ORIGIN，而不是站点地址。

    官方部署里站点在 hoa.moe、API 在 api.hoa.moe，
    meta 里给出的 base_url / mcp_endpoint 必须指向 API 本身。
    """
    config = Config(
        db_path=":memory:",
        rate_limit_per_min=1000,
        site_origin="https://hoa.moe",
        public_origin="https://api.hoa.moe",
    )
    store = Store(config.db_path)
    service = Service(store, config)
    meta = service.meta()
    assert meta["base_url"] == "https://api.hoa.moe/api/v1"
    assert meta["mcp_endpoint"] == "https://api.hoa.moe/mcp"
    store.close()


def test_list_courses(client):
    data = client.get("/api/v1/courses?q=机器人").json()
    assert data["total"] == 1
    assert data["items"][0]["code"] == "AUTO3005"
    assert data["items"][0]["teachers"] == ["楼云江"]


def test_get_course(client):
    data = client.get("/api/v1/courses/AUTO3005").json()
    assert data["name"] == "机器人学导论"
    assert data["sections"][0]["title"] == "教材"
    assert data["lecturers"]["items"][0]["name"] == "楼云江"


def test_get_course_not_found(client):
    resp = client.get("/api/v1/courses/NOPE")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_get_course_readme(client):
    resp = client.get("/api/v1/courses/AUTO3005/readme")
    assert resp.status_code == 200
    assert "机器人学导论" in resp.text

    resp = client.get("/api/v1/courses/AUTO3005/readme?format=toml")
    assert resp.status_code == 200
    assert "course_name" in resp.text


def test_get_course_materials(client):
    data = client.get("/api/v1/courses/AUTO3005/materials").json()
    assert data["code"] == "AUTO3005"
    assert data["nodes"][0]["name"] == "exams"


def test_teachers(client):
    data = client.get("/api/v1/teachers?q=楼").json()
    assert data["items"][0]["name"] == "楼云江"


def test_grading(client):
    data = client.get("/api/v1/grades/AUTO3005").json()
    assert data["code"] == "AUTO3005"
    assert data["items"][0]["name"] == "作业"


def test_search(client):
    data = client.get("/api/v1/search?q=机器人").json()
    assert data["total"] >= 1
    assert data["items"][0]["type"] == "course"


def test_etag_roundtrip(client):
    resp = client.get("/api/v1/courses")
    etag = resp.headers["etag"]
    again = client.get("/api/v1/courses", headers={"If-None-Match": etag})
    assert again.status_code == 304


def test_api_version_header(client):
    resp = client.get("/api/v1/meta")
    assert resp.headers["x-hoa-api-version"] == "v1"


def test_compat_courses_search(client):
    """兼容 course-server 的响应信封。"""
    resp = client.post("/v1/courses:search", json={"keyword": "机器人", "limit": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["results"][0]["code"] == "AUTO3005"
    assert data["data"]["results"][0]["org"] == "HITSZ-OpenAuto"
    assert data["data"]["results"][0]["teachers"] == ["楼云江"]


def test_compat_courses_search_ignores_limit(client):
    """老 course-server 忽略请求里的 limit，兼容层必须保持同样语义。

    否则 HIT-A 传 limit=10 时，新服务只会返回 10 条而老服务返回全部命中。
    """
    for limit in (1, 5, 100):
        resp = client.post("/v1/courses:search", json={"keyword": "机器人", "limit": limit})
        results = resp.json()["data"]["results"]
        assert len(results) == 1, f"limit={limit} 时结果条数被裁剪了"


def test_compat_courses_search_nickname_fallback(tmp_path):
    """昵称回落：直接匹配不到时，用昵称表还原官方课程名再匹配。

    「高数」不是任何课程名，但它是「微积分」的常见叫法——老 course-server
    靠昵称表命中，这里必须一致，否则 HIT-A 切流后同样的提问会查不到课。
    """
    config = Config(db_path=str(tmp_path / "nick.db"), rate_limit_per_min=1000)
    store = Store(config.db_path)
    store.upsert_course(
        {
            "code": "MATH1001",
            "repo": "MATH1001",
            "name": "微积分",
            "description": "",
            "repo_type": "normal",
            "aliases": [],
            "teachers": [],
            "sections": [],
            "lecturers": {},
            "grading": {},
            "readme_md": "",
            "readme_toml": "",
            "source_commit": "abc",
            "source_updated": "2026-10-14T00:00:00Z",
            "synced_at": "2026-11-06T00:00:00Z",
            "materials": [],
        }
    )
    store.commit()
    app = create_app(config, store)
    with TestClient(app) as test_client:
        results = test_client.post("/v1/courses:search", json={"keyword": "高数"}).json()["data"][
            "results"
        ]
        assert results[0]["code"] == "MATH1001"
    store.close()


def test_compat_course_read(client):
    resp = client.post(
        "/v1/course:read",
        json={"target": {"campus": "shenzhen", "course_code": "AUTO3005"}},
    )
    data = resp.json()
    assert data["ok"] is True
    assert "机器人学导论" in data["data"]["result"]["readme_md"]
    assert "readme_toml" not in data["data"]["result"]

    resp = client.post(
        "/v1/course:read",
        json={
            "target": {"campus": "shenzhen", "course_code": "AUTO3005"},
            "include_toml": True,
        },
    )
    assert "readme_toml" in resp.json()["data"]["result"]


def test_compat_course_read_not_found(client):
    resp = client.post(
        "/v1/course:read",
        json={"target": {"campus": "shenzhen", "course_code": "NOPE"}},
    )
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "COURSE_NOT_FOUND"


def test_compat_layer_has_wider_rate_limit(tmp_path):
    """兼容层限流阈值必须比公开 API 宽。

    旧 course-server 只在 localhost 提供服务且不限流；HIT-A 切过来后如果
    被公开 API 的阈值拦成 429，就是一次真实的行为回归。
    """
    config = Config(
        db_path=str(tmp_path / "limit.db"),
        rate_limit_per_min=2,
        compat_rate_limit_per_min=50,
    )
    store = Store(config.db_path)
    app = create_app(config, store)
    with TestClient(app) as test_client:
        public_codes = [
            test_client.get("/api/v1/courses").status_code for _ in range(6)
        ]
        compat_codes = [
            test_client.post(
                "/v1/courses:search", json={"keyword": "机器人"}
            ).status_code
            for _ in range(6)
        ]
    store.close()

    assert 429 in public_codes, "公开 API 的限流应当生效"
    assert 429 not in compat_codes, "兼容层不应被公开 API 的阈值拦成 429"
