"""REST 路由与兼容层测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hoa_api.api import create_app
from hoa_api.config import Config
from hoa_api.db import Store


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
