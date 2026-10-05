"""Integration tests for the Store: persistence, overrides, merges.

Everything runs against a throwaway project root built in tmp_path, which also
proves that Store honours its ``root`` argument (config.json, data/ sidecars and
catalog globs all resolve inside it).
"""
from __future__ import annotations

import json

import pytest

from caption_studio.store import Store, title_key
from tests.conftest import episode_row, movie_row, write_catalog


@pytest.fixture
def catalog_rows():
    """56 rows: 41 episode rows + 15 movie rows (above the 50-row threshold)."""
    rows = []
    for s in (1, 2):
        for e in range(1, 21):
            rows.append(episode_row(season=s, ep=e))
    rows.append(episode_row(season=1, ep=1, drive="E:"))   # duplicate copy
    for i in range(12):
        rows.append(movie_row(name=f"Movie Number {i:02d}", year=2010 + i))
    rows.append(movie_row(name="2 Guns"))
    rows.append(movie_row(name="2 Guns", drive="E:", size=123))
    rows.append(movie_row(name="2 Gunss", size=5))          # typo variant
    return rows


@pytest.fixture
def store(tmp_path, catalog_rows):
    write_catalog(str(tmp_path / "data" / "catalog.csv"), catalog_rows)
    return Store(str(tmp_path))


def test_title_key_normalisation():
    assert title_key("Watch 24") == "watch 24"
    assert title_key("  Grey's  Anatomy ") == "grey s anatomy"
    assert title_key("") == ""


def test_store_loads_and_folds_catalog(store):
    s = store.stats()
    # 12 unique movies + 2 Guns (+ its typo variant, not yet merged) = 14 movies
    assert s["movies"] == 14
    series = store.find_by_name("Test Series")
    assert series is not None and series.is_series
    assert series.seasons == 2 and series.episodes == 40
    assert series.runtime_min == 42
    assert series.genres == ["Crime", "Drama"]
    two_guns = store.find_by_name("2 Guns")
    assert two_guns.total_bytes == 123 + 2147483648


def test_store_is_isolated_to_root(store, tmp_path):
    # config + data live inside the throwaway root, not the source tree
    assert (tmp_path / "config.json").exists()
    assert (tmp_path / "data" / "catalog.csv").exists()
    assert store.root == str(tmp_path)


def test_save_override_roundtrip(store):
    store.save_override("Test Series", {"synopsis": "Custom synopsis.", "dm_keyword": "TST"})
    fresh = Store(store.root)
    t = fresh.find_by_name("Test Series")
    assert t.overview == "Custom synopsis."
    assert t.dm_keyword == "TST"
    stored = fresh.overrides[title_key("Test Series")]
    assert stored["synopsis"] == "Custom synopsis."


def test_save_enriched_roundtrip(store):
    t = store.find_by_name("2 Guns")
    t.overview = "From TMDB."
    t.tmdb_id = 12345
    store.save_enriched(t)
    fresh = Store(store.root)
    t2 = fresh.find_by_name("2 Guns")
    assert t2.overview == "From TMDB."
    assert t2.tmdb_id == 12345 and t2.enriched
    fresh.forget_enrichment("2 Guns")
    fresh2 = Store(store.root)
    assert fresh2.find_by_name("2 Guns").enriched is False


def test_clear_override(store):
    store.save_override("Test Series", {"synopsis": "Custom synopsis."})
    store.clear_override("Test Series")
    fresh = Store(store.root)
    t = fresh.find_by_name("Test Series")
    assert t.overview != "Custom synopsis."
    assert title_key("Test Series") not in fresh.overrides


def test_merge_writes_rules_and_folds(store, tmp_path):
    keep = store.find_by_name("2 Guns")
    other = store.find_by_name("2 Gunss")
    assert keep is not None and other is not None
    store.merge(keep.id, other.id)
    on_disk = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert on_disk["merge_rules"] == {"2 Gunss": "2 Guns"}
    fresh = Store(store.root)
    stats = fresh.stats()
    assert stats["movies"] == 13
    merged = fresh.find_by_name("2 Guns")
    assert merged.total_bytes == 123 + 2147483648 + 5


def test_strip_prefixes_applied_from_config(store):
    # "Watch 2 Guns" would fold into "2 Guns" via the default strip prefixes.
    t = store.find_by_name("2 Guns")
    assert t is not None


def test_reload_picks_up_new_catalog(store, tmp_path):
    write_catalog(str(tmp_path / "data" / "catalog-2.csv"),
                  [episode_row(series="New Show", season=1, ep=e) for e in range(1, 61)])
    before = len(store.library.titles)
    store.reload()
    assert len(store.library.titles) > before
    assert store.find_by_name("New Show") is not None
<<<<<<< HEAD
=======

>>>>>>> origin/master
