"""Tests for caption_studio.config."""
from __future__ import annotations

import json

from caption_studio.config import Config, _deep_merge


def test_deep_merge_nested_dicts():
    base = {"a": {"x": 1, "y": 2}, "b": 1}
    extra = {"a": {"y": 9, "z": 3}, "c": 4}
    merged = _deep_merge(base, extra)
    assert merged["a"] == {"x": 1, "y": 9, "z": 3}
    assert merged["b"] == 1
    assert merged["c"] == 4
    # inputs untouched
    assert base["a"]["y"] == 2


def test_load_missing_file_creates_defaults(tmp_path):
    path = tmp_path / "config.json"
    cfg = Config.load(str(path))
    assert path.exists()
    assert cfg.brand == "Plugent"
    assert json.loads(path.read_text(encoding="utf-8"))["brand"] == "Plugent"


def test_load_reads_file_and_merges_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"brand": "Acme", "icons": {"why": "🔥"}}),
                    encoding="utf-8")
    cfg = Config.load(str(path))
    assert cfg.brand == "Acme"
    # partial icon override merges over the shipped defaults
    assert cfg.icon("why") == "🔥"
    assert cfg.icon("synopsis") == "📖"
    # sections unaffected by the icons patch
    assert cfg.sections["cta"] is True


def test_update_persists_to_disk(tmp_path):
    path = tmp_path / "config.json"
    cfg = Config.load(str(path))
    cfg.update({"brand": "Y", "cta_tail": "ready to flash"})
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["brand"] == "Y"
    assert on_disk["cta_tail"] == "ready to flash"


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    cfg = Config.load(str(path))
    assert cfg.brand == "Plugent"


def test_sections_partial_override(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"sections": {"trailer": False}}), encoding="utf-8")
    cfg = Config.load(str(path))
    assert cfg.sections["trailer"] is False
    assert cfg.sections["synopsis"] is True
<<<<<<< HEAD
=======

>>>>>>> origin/master
