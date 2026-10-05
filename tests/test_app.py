"""Tests for the web API: catalog import and trailer repair."""
from __future__ import annotations

import csv
import io
import json

from fastapi.testclient import TestClient

from caption_studio.app import create_app
from caption_studio.store import Store, title_key
from tests.conftest import CSV_FIELDS, episode_row, write_catalog


def _csv_bytes(rows) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _client(tmp_path) -> TestClient:
    return TestClient(create_app(str(tmp_path)))


def test_upload_catalog_saves_and_reloads(tmp_path):
    client = _client(tmp_path)
    rows = [episode_row(season=1, ep=e) for e in range(1, 61)]
    resp = client.post("/api/catalogs", files={
        "file": ("catalog-new.csv", _csv_bytes(rows), "text/csv")})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True and data["loaded"] is True
    assert data["stats"]["titles"] == 1
    assert data["sources"] == ["catalog-new.csv"]
    assert (tmp_path / "data" / "catalog-new.csv").exists()
    # the imported title is immediately searchable through the API
    found = client.get("/api/titles", params={"q": "Test Series"}).json()
    assert found["total"] == 1


def test_upload_rejects_non_csv(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/api/catalogs", files={
        "file": ("notes.txt", b"hello world", "text/plain")})
    assert resp.status_code == 400
    assert ".csv" in resp.json()["detail"]


def test_upload_rejects_empty_file(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/api/catalogs", files={
        "file": ("empty.csv", b"", "text/csv")})
    assert resp.status_code == 400


def test_upload_sanitises_path_traversal(tmp_path):
    client = _client(tmp_path)
    rows = [episode_row(season=1, ep=e) for e in range(1, 61)]
    resp = client.post("/api/catalogs", files={
        "file": ("../../evil.csv", _csv_bytes(rows), "text/csv")})
    assert resp.status_code == 200
    # stored flat inside data/, never outside it
    assert (tmp_path / "data" / "evil.csv").exists()
    assert not (tmp_path / "evil.csv").exists()


def test_upload_warns_when_format_is_ignored(tmp_path):
    """A valid CSV that doesn't match the scanner schema is saved but flagged."""
    client = _client(tmp_path)
    body = b"name,year\nSome Film,2001\n"
    resp = client.post("/api/catalogs", files={
        "file": ("handmade.csv", body, "text/csv")})
    assert resp.status_code == 200
    data = resp.json()
    assert data["loaded"] is False
    assert data["stats"]["titles"] == 0


def test_reuploading_same_name_overwrites(tmp_path):
    client = _client(tmp_path)
    rows = [episode_row(season=1, ep=e) for e in range(1, 61)]
    client.post("/api/catalogs", files={
        "file": ("catalog.csv", _csv_bytes(rows[:10] + rows), "text/csv")})
    resp = client.post("/api/catalogs", files={
        "file": ("catalog.csv", _csv_bytes(rows), "text/csv")})
    assert resp.status_code == 200 and resp.json()["loaded"] is True
    on_disk = (tmp_path / "data" / "catalog.csv").read_bytes()
    assert _csv_bytes(rows) == on_disk


def test_reload_endpoint_re_scans_data_dir(tmp_path):
    client = _client(tmp_path)
    assert client.post("/api/reload", json={}).json()["stats"]["titles"] == 0
    write_catalog(str(tmp_path / "data" / "later.csv"),
                  [episode_row(season=1, ep=e) for e in range(1, 61)])
    data = client.post("/api/reload", json={}).json()
    assert data["stats"]["titles"] == 1
    assert data["sources"] == ["later.csv"]


# -- trailer check / fix ----------------------------------------------------------
def _seed_dead_trailer(tmp_path) -> None:
    """Catalog + an enriched title whose stored trailer link is dead."""
    write_catalog(str(tmp_path / "data" / "catalog.csv"),
                  [episode_row(season=1, ep=e) for e in range(1, 51)])
    (tmp_path / "data" / "enriched.json").write_text(json.dumps({
        title_key("Test Series"): {"trailer_url": "https://youtu.be/deaddeaddea"}
    }), encoding="utf-8")


def test_trailer_check_finds_dead_links(tmp_path, monkeypatch):
    _seed_dead_trailer(tmp_path)
    client = _client(tmp_path)
    monkeypatch.setattr("caption_studio.app.youtube_ok",
                        lambda u, **kw: "dead" not in (u or ""))
    r = client.post("/api/trailers/check").json()
    assert r["checked"] == 1 and r["ok"] == 0
    assert len(r["dead"]) == 1
    assert r["dead"][0]["name"] == "Test Series"


def test_trailer_check_all_good(tmp_path, monkeypatch):
    _seed_dead_trailer(tmp_path)
    client = _client(tmp_path)
    monkeypatch.setattr("caption_studio.app.youtube_ok", lambda u, **kw: True)
    r = client.post("/api/trailers/check").json()
    assert r["ok"] == 1 and r["dead"] == []


def test_trailer_fix_removes_dead_link_without_key(tmp_path, monkeypatch):
    _seed_dead_trailer(tmp_path)
    monkeypatch.delenv("TMDB_API_KEY", raising=False)  # hermetic: no real TMDB call
    client = _client(tmp_path)
    monkeypatch.setattr("caption_studio.app.youtube_ok",
                        lambda u, **kw: "dead" not in (u or ""))
    f = client.post("/api/trailers/fix").json()
    # no TMDB key in the test config -> dead link is cleared, not replaced
    assert f["dead_found"] == 1 and len(f["removed"]) == 1 and not f["replaced"]
    assert f["removed"][0]["name"] == "Test Series"
    # persisted: a fresh store no longer has the dead URL
    fresh = Store(str(tmp_path))
    assert fresh.find_by_name("Test Series").trailer_url is None

