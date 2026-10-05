"""Tests for trailer link validation, ranking and repair (tmdb + store)."""
from __future__ import annotations

import time
import urllib.error

import pytest

from caption_studio.store import Store, title_key
from caption_studio.tmdb import TMDBClient, rank_trailers, youtube_ok, youtube_video_id
from tests.conftest import episode_row, write_catalog


# -- URL parsing ---------------------------------------------------------------
def test_youtube_video_id_shapes():
    assert youtube_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert youtube_video_id("https://youtube.com/watch?list=x&v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert youtube_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert youtube_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert youtube_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    # non-YouTube links can't be checked — they parse as None (=> accepted)
    assert youtube_video_id("https://vimeo.com/12345") is None
    assert youtube_video_id("") is None
    assert youtube_video_id(None) is None


# -- validation ----------------------------------------------------------------
class _Resp:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(monkeypatch, http=None, error=None):
    calls = []

    def fake(url, timeout=None):
        calls.append(url)
        if error is not None:
            raise error
        return _Resp(http)

    monkeypatch.setattr("urllib.request.urlopen", fake)
    return calls


def test_youtube_ok_accepts_live_video(monkeypatch, tmp_path):
    calls = _fake_urlopen(monkeypatch, http=200)
    assert youtube_ok("dQw4w9WgXcQ", cache_dir=str(tmp_path)) is True
    assert len(calls) == 1
    # cached: second check makes no network call
    assert youtube_ok("dQw4w9WgXcQ", cache_dir=str(tmp_path)) is True
    assert len(calls) == 1


def test_youtube_ok_flags_missing_video(monkeypatch, tmp_path):
    _fake_urlopen(monkeypatch, http=404)
    assert youtube_ok("zzzzzzzzzzz", cache_dir=str(tmp_path)) is False
    # dead verdict is cached too
    assert youtube_ok("zzzzzzzzzzz", cache_dir=str(tmp_path)) is False


def test_youtube_ok_network_error_is_unknown_and_uncached(monkeypatch, tmp_path):
    calls = _fake_urlopen(monkeypatch, error=urllib.error.URLError("no net"))
    # unknown => accepted
    assert youtube_ok("dQw4w9WgXcQ", cache_dir=str(tmp_path)) is True
    # ...and not cached, so a later check can retry
    assert youtube_ok("dQw4w9WgXcQ", cache_dir=str(tmp_path)) is True
    assert len(calls) == 2


def test_youtube_ok_skips_non_youtube_links(tmp_path):
    # no network: a fake URL never reaches urlopen
    assert youtube_ok("https://example.com/trailer.mp4", cache_dir=str(tmp_path)) is True
    assert youtube_ok("", cache_dir=str(tmp_path)) is True


def test_youtube_ok_fresh_cache_expires(monkeypatch, tmp_path):
    calls = _fake_urlopen(monkeypatch, http=200)
    assert youtube_ok("dQw4w9WgXcQ", cache_dir=str(tmp_path)) is True
    # age the cache entry past the TTL
    cpath = tmp_path / "yt_dQw4w9WgXcQ.json"
    old = time.time() - 40 * 86400
    import os
    os.utime(cpath, (old, old))
    assert youtube_ok("dQw4w9WgXcQ", cache_dir=str(tmp_path)) is True
    assert len(calls) == 2


# -- ranking ---------------------------------------------------------------------
def _video(key, vtype, official=True, iso="en", site="YouTube"):
    return {"site": site, "key": key, "type": vtype, "official": official,
            "iso_639_1": iso}


def test_rank_prefers_official_trailer():
    ranked = rank_trailers([
        _video("aaaaaaaaaaa", "teaser", official=True),
        _video("bbbbbbbbbbb", "trailer", official=False),
        _video("ccccccccccc", "trailer", official=True),
        _video("ddddddddddd", "trailer", official=True, site="Vimeo"),
    ], "en-US")
    keys = [v["key"] for v in ranked]
    assert keys[0] == "ccccccccccc"     # official trailer
    assert keys[1] == "bbbbbbbbbbb"     # any trailer beats an official teaser
    assert keys[2] == "aaaaaaaaaaa"
    assert "ddddddddddd" not in keys     # non-YouTube dropped


def test_rank_prefers_configured_language():
    ranked = rank_trailers([
        _video("germandeutsch", "trailer", official=True, iso="de"),
        _video("englishenglish", "trailer", official=True, iso="en"),
    ], "en-US")
    assert ranked[0]["key"] == "englishenglish"


def test_rank_sinks_unknown_types_and_empty():
    ranked = rank_trailers([
        _video("behindthescen", "Behind The Scenes"),
        _video("sometrailerx", "trailer"),
        _video("fanuploadxx1", "somethingweird"),
    ], "en-US")
    # known types rank ahead of unknown ones
    assert [v["type"] for v in ranked] == ["trailer", "Behind The Scenes",
                                           "somethingweird"]
    assert rank_trailers(None) == []
    assert rank_trailers([{"site": "YouTube"}]) == []   # no key -> dropped


# -- TMDBClient trailer pick ------------------------------------------------------
@pytest.fixture
def client(tmp_path):
    return TMDBClient("test-key", "en-US", cache_dir=str(tmp_path / "cache"))


def test_trailer_skips_dead_candidate(monkeypatch, client):
    client._get = lambda path, **kw: {"results": [
        _video("deaddeaddea", "trailer", official=True),
        _video("alivealive12", "trailer", official=True),
    ]}
    monkeypatch.setattr("caption_studio.tmdb.youtube_ok",
                        lambda v, **kw: v != "deaddeaddea")
    assert client._trailer("movie", 1) == "https://youtu.be/alivealive12"


def test_trailer_all_candidates_dead_returns_none(monkeypatch, client):
    client._get = lambda path, **kw: {"results": [
        _video("deaddeaddea", "trailer"),
        _video("alsodead123", "teaser"),
    ]}
    monkeypatch.setattr("caption_studio.tmdb.youtube_ok", lambda v, **kw: False)
    assert client._trailer("movie", 1) is None


def test_trailer_refresh_bypasses_cache(client):
    seen = {}

    def fake_get(path, **kw):
        seen[path] = kw
        return {"results": []}

    client._get = fake_get
    client._trailer("movie", 7)
    client._trailer("movie", 7, refresh=True)
    assert seen["/movie/7/videos"].get("ttl_days") == 0


# -- Store.repair_trailer ----------------------------------------------------------
@pytest.fixture
def store(tmp_path):
    rows = [episode_row(season=1, ep=e) for e in range(1, 51)]
    write_catalog(str(tmp_path / "data" / "catalog.csv"), rows)
    return Store(str(tmp_path))


def test_repair_clears_dead_link_from_both_sidecars(store):
    t = store.find_by_name("Test Series")
    t.trailer_url = "https://youtu.be/deaddeaddea"
    store.save_enriched(t)
    store.save_override(t.name, {"trailer": "https://youtu.be/deaddeaddea"})

    store.repair_trailer(t.name, None)

    # in-memory, immediately
    assert store.find_by_name("Test Series").trailer_url is None
    # ...and on a fresh load from disk
    fresh = Store(store.root)
    assert fresh.find_by_name("Test Series").trailer_url is None
    assert fresh.overrides.get(title_key(t.name), {}).get("trailer") is None
    assert fresh.enriched[title_key(t.name)].get("trailer_url") is None


def test_repair_stores_valid_replacement(store):
    t = store.find_by_name("Test Series")
    t.trailer_url = "https://youtu.be/deaddeaddea"
    store.save_enriched(t)

    store.repair_trailer(t.name, "https://youtu.be/alivealive12")

    assert store.find_by_name("Test Series").trailer_url == "https://youtu.be/alivealive12"
    fresh = Store(store.root)
    assert fresh.find_by_name("Test Series").trailer_url == "https://youtu.be/alivealive12"
<<<<<<< HEAD
=======

>>>>>>> origin/master
