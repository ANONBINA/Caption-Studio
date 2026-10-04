"""Regression and integration coverage for the first incremental upgrade."""
import io
import json
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from caption_studio.app import create_app
from caption_studio.backups import Backups
from caption_studio.catalog import Library
from caption_studio.export import spreadsheet_safe
from caption_studio.jobs import JobManager
from caption_studio.models import Title
from caption_studio.store import Store
from tests.conftest import movie_row, write_catalog


@pytest.fixture
def upgraded(tmp_path):
    rows = [movie_row(name=f"Film {i:03}", year=1980 + i % 40,
                      size=(i + 1) * 10000000) for i in range(75)]
    write_catalog(str(tmp_path / "data" / "catalog.csv"), rows)
    with TestClient(create_app(str(tmp_path))) as client:
        yield client, tmp_path


def wait_job(client, ident):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{ident}").json()
        if job["status"] not in ("running", "queued"):
            return job
        time.sleep(.02)
    pytest.fail("Job failed to finish within 10 seconds")


def test_sort_before_pagination_and_detail_only_paths(upgraded):
    client, _ = upgraded
    first = client.get("/api/titles?sort=size&limit=10").json()
    second = client.get("/api/titles?sort=size&limit=10&offset=10").json()
    assert first["total"] == 75
    assert first["items"][0]["name"] == "Film 074"
    assert second["items"][0]["name"] == "Film 064"
    assert first["next_offset"] == 10
    assert "files" not in first["items"][0]
    detail = client.get("/api/titles/" + first["items"][0]["id"]).json()
    assert detail["files"]


@pytest.mark.parametrize("query", ["limit=-1", "offset=-2", "limit=501", "sort=bogus",
                                   "year_min=2000&year_max=1990"])
def test_search_input_validation(upgraded, query):
    client, _ = upgraded
    assert client.get("/api/titles?" + query).status_code == 422


def test_faceted_search(upgraded):
    client, _ = upgraded
    result = client.get("/api/titles?year_min=2010&language=English&enriched=false").json()
    assert result["total"] > 0
    assert all(t["year"] >= 2010 for t in result["items"])
    assert client.get("/api/titles?q=Action").json()["total"] == 75
    assert "English" in client.get("/api/facets").json()["languages"]


def test_caption_save_and_export_match_preview(upgraded):
    client, root = upgraded
    ident = client.get("/api/titles?limit=1").json()["items"][0]["id"]
    assert client.post(f"/api/titles/{ident}/override", json={
        "why": "A unique hand-edited recommendation.", "bullets": ["Custom highlight"]
    }).status_code == 200
    preview = client.post(f"/api/caption/{ident}", json={}).json()["text"]
    saved = client.post(f"/api/caption/{ident}/save", json={}).json()["path"]
    from pathlib import Path
    assert Path(saved).read_text(encoding="utf-8") == preview
    response = client.post("/api/jobs", json={"ids": [ident],
                                            "formats": ["txt", "md", "html", "json", "csv"]})
    assert response.status_code == 202
    job = wait_job(client, response.json()["id"])
    assert job["status"] == "completed" and job["completed"] == 1
    download = client.get(f"/api/jobs/{job['id']}/download")
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        name = next(n for n in archive.namelist() if n.endswith(".txt"))
        assert archive.read(name).decode() == preview
        assert len(archive.namelist()) == 6
        assert "captions.csv" in archive.namelist()
    assert (root / "exports" / job["id"] / "status.json").exists()


def test_job_request_validation(upgraded):
    client, _ = upgraded
    for payload in ({"formats": []}, {"formats": ["exe"]}, {"limit": 5001},
                    {"options": {"overrides": {"bullets": 123}}}):
        assert client.post("/api/jobs", json=payload).status_code == 422
    assert client.post("/api/jobs", json={"ids": ["missing"]}).status_code == 404
    assert client.post("/api/jobs", json={"q": "not a title"}).status_code == 400
    assert client.get("/api/jobs/missing/download").status_code == 404
    assert client.get("/api/caption/missing?style=nonsense").status_code == 422


def test_backup_round_trip(upgraded):
    client, root = upgraded
    original = client.get("/api/settings").json()["brand"]
    snapshot = client.post("/api/backups").json()["id"]
    client.post("/api/settings", json={"brand": "Changed"})
    extra = root / "data" / "extra.json"
    extra.write_text('{}')
    assert client.post(f"/api/backups/{snapshot}/restore", json={}).status_code == 422
    result = client.post(f"/api/backups/{snapshot}/restore", json={"confirm": "RESTORE"})
    assert result.status_code == 200
    assert result.json()["safety_backup"] != snapshot
    assert client.get("/api/settings").json()["brand"] == original
    assert not extra.exists()
    assert client.get(f"/api/backups/{snapshot}/download").status_code == 200


def test_tampered_backup_does_not_change_state(tmp_path):
    store = Store(str(tmp_path))
    backups = Backups(store)
    snapshot = backups.create()["id"]
    path = backups.path(snapshot)
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("config.json", '{"brand":"tampered"}')
    before = (tmp_path / "config.json").read_bytes()
    with pytest.raises(ValueError, match="checksum"):
        backups.restore(snapshot)
    assert (tmp_path / "config.json").read_bytes() == before
    with pytest.raises(ValueError):
        backups.path("../../config")


def test_cross_site_writes_blocked(upgraded):
    client, _ = upgraded
    assert client.post("/api/settings", json={"brand": "bad"},
                       headers={"Origin": "https://attacker.example"}).status_code == 403
    assert client.post("/api/settings", json={"brand": "Good"},
                       headers={"Origin": "http://testserver"}).status_code == 200
    assert client.post("/api/reload", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/api/reload").status_code == 405
    assert client.get("/api/health").headers["x-content-type-options"] == "nosniff"


def test_atomic_concurrent_sidecar_updates(tmp_path):
    store = Store(str(tmp_path))
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda n: store.save_override(f"Film {n}", {"why": f"Copy {n}"}), range(40)))
    assert len(json.loads((tmp_path / "data" / "overrides.json").read_text())) == 40


def test_interrupted_jobs_marked_on_restart(tmp_path):
    directory = tmp_path / "exports" / "abcd"
    directory.mkdir(parents=True)
    (directory / "status.json").write_text(json.dumps({"id": "abcd", "status": "running"}))
    manager = JobManager(tmp_path)
    assert manager.get("abcd")["status"] == "interrupted"
    manager.close()


def test_job_queue_bound_and_cancellation(tmp_path):
    manager = JobManager(tmp_path)
    gate = threading.Event()
    started = threading.Event()

    def render(title):
        started.set()
        gate.wait(3)
        raise RuntimeError("should be ignored after cancellation")

    title = Title(id="a", kind="movie", name="Film")
    try:
        jobs = [manager.submit([title], render, ["txt"]) for _ in range(4)]
        assert started.wait(1)
        with pytest.raises(ValueError):
            manager.submit([title], render, ["txt"])
        for job in jobs:
            manager.cancel(job["id"])
    finally:
        gate.set()
        manager.close()
    assert all(manager.get(j["id"])["status"] == "cancelled" for j in jobs)


def test_spreadsheet_formula_escape():
    assert spreadsheet_safe(" =HYPERLINK(1)").startswith("'")
    assert spreadsheet_safe("Normal caption") == "Normal caption"
    assert spreadsheet_safe(2000) == 2000


def test_search_stable_ties():
    library = Library([Title(id="b", kind="movie", name="Same", year=2000),
                       Title(id="a", kind="movie", name="Same", year=2000)], [])
    assert library.search(sort="year", limit=1)[0][0].id == "a"


def test_untrusted_host_blocked(upgraded):
    client, _ = upgraded
    assert client.get("/api/settings", headers={"Host": "attacker.example"}).status_code == 400


def test_caption_provider_hook(tmp_path):
    from caption_studio.providers import TemplateCaptionProvider

    class CustomProvider(TemplateCaptionProvider):
        name = "test-provider"

        def generate(self, title, config, options):
            caption = super().generate(title, config, options)
            caption.text = "Custom provider output"
            return caption

    write_catalog(str(tmp_path / "data" / "catalog.csv"),
                  [movie_row(name=f"Title {i}") for i in range(50)])
    with TestClient(create_app(str(tmp_path), caption_provider=CustomProvider())) as client:
        assert client.get("/api/health").json()["caption_provider"] == "test-provider"
        ident = client.get("/api/titles?limit=1").json()["items"][0]["id"]
        assert client.get(f"/api/caption/{ident}").json()["text"] == "Custom provider output"
