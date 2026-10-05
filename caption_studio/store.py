"""Persistent state: config, the loaded library, TMDB enrichment and overrides.

Enrichment and hand-written overrides are stored in ``data/`` keyed by title
name, so they survive a library rebuild after you drop in a newer catalog CSV.
"""
from __future__ import annotations

import glob
import json
import os
import re
import tempfile
import threading
from functools import wraps
from typing import Any, Dict, List, Optional

from .catalog import Library, duplicate_candidates
from .config import Config
from .models import Title

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_json(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    return {}


def _save_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def synchronized(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapped


def title_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


class Store:
    def __init__(self, root: Optional[str] = None):
        # None means "this project" — resolved to an absolute path so data
        # globs and config loading never depend on the current directory.
        self.root = os.path.abspath(root or ROOT)
        # Everything lives under ``root`` so a Store pointed elsewhere (the
        # CLI's --root flag, tests) is fully isolated from the source tree.
        data_dir = os.path.join(self.root, "data")
        os.makedirs(data_dir, exist_ok=True)
        self.enriched_path = os.path.join(data_dir, "enriched.json")
        self.overrides_path = os.path.join(data_dir, "overrides.json")
        self.config = Config.load(os.path.join(self.root, "config.json"))
        self.enriched: Dict[str, Any] = _load_json(self.enriched_path)
        self.overrides: Dict[str, Any] = _load_json(self.overrides_path)
        self.library: Library = Library([], [])
        self._lock = threading.RLock()
        self.reload()

    # -- lifecycle --------------------------------------------------------
    @synchronized
    def reload(self) -> None:
        # catalog_glob may be relative ("data/*.csv") — resolve it against the
        # store's root, never the current working directory.
        raw = self.config.get("catalog_glob", "data/*.csv")
        patterns = [raw if os.path.isabs(raw) else os.path.join(self.root, raw)]
        if not any(glob.glob(p) for p in patterns):
            patterns = [os.path.join(self.root, "data", "*.csv")]
        self.library = Library.load(
            patterns,
            self.config.get("merge_rules") or {},
            strip_prefixes=self.config.get("strip_prefixes") or [])
        self._apply_sidecars()

    def _apply_sidecars(self) -> None:
        for t in self.library.titles:
            key = title_key(t.name)
            data = self.enriched.get(key)
            if data:
                for field in ("overview", "tagline", "rating", "trailer_url",
                              "poster_url", "tmdb_id"):
                    if data.get(field):
                        setattr(t, field, data[field])
                if data.get("cast"):
                    t.cast = list(data["cast"])
                if data.get("genres"):
                    t.genres = list(data["genres"])[:3]
                if data.get("year"):
                    t.year = data["year"]
                if data.get("year_end"):
                    t.year_end = data["year_end"]
                if data.get("seasons"):
                    t.seasons = data["seasons"]
                if data.get("episodes"):
                    t.episodes = data["episodes"]
                if data.get("runtime_min"):
                    t.runtime_min = data["runtime_min"]
                t.enriched = True
            ov = self.overrides.get(key)
            if ov:
                t.dm_keyword = ov.get("dm_keyword") or t.dm_keyword
                if ov.get("synopsis"):
                    t.overview = ov["synopsis"]
                if ov.get("tagline"):
                    t.tagline = ov["tagline"]
                if ov.get("rating"):
                    t.rating = ov["rating"]
                if ov.get("trailer"):
                    t.trailer_url = ov["trailer"]
                if ov.get("genres"):
                    t.genres = [g.strip() for g in re.split(r"[,|]", ov["genres"])
                                if g.strip()][:3]
                if ov.get("cast"):
                    t.cast = [c.strip() for c in re.split(r"[|]", ov["cast"])
                              if c.strip()]

    # Fields that may legitimately be saved as empty (i.e. cleared).
    CLEARABLE = {"bullets", "genres", "cast"}

    # -- persistence -------------------------------------------------------
    @synchronized
    def save_enriched(self, title: Title) -> None:
        key = title_key(title.name)
        self.enriched[key] = {
            "overview": title.overview, "tagline": title.tagline, "cast": title.cast,
            "rating": title.rating, "trailer_url": title.trailer_url,
            "poster_url": title.poster_url, "tmdb_id": title.tmdb_id,
            "genres": title.genres, "year": title.year, "year_end": title.year_end,
            "seasons": title.seasons, "episodes": title.episodes,
            "runtime_min": title.runtime_min,
        }
        _save_json(self.enriched_path, self.enriched)

    @synchronized
    def save_override(self, name: str, patch: Dict[str, Any]) -> None:
        key = title_key(name)
        entry = self.overrides.setdefault(key, {})
        entry.update({k: v for k, v in patch.items()
                      if v not in (None, "", []) or k in self.CLEARABLE})
        _save_json(self.overrides_path, self.overrides)
        t = self.find_by_name(name)
        if t is not None:
            t.dm_keyword = entry.get("dm_keyword") or t.dm_keyword
            if entry.get("synopsis"):
                t.overview = entry["synopsis"]
            if entry.get("tagline"):
                t.tagline = entry["tagline"]
            if entry.get("genres"):
                t.genres = [g.strip() for g in re.split(r"[,|]", entry["genres"]) if g.strip()][:3]
            if entry.get("cast"):
                t.cast = [c.strip() for c in re.split(r"[|]", entry["cast"]) if c.strip()]
            if entry.get("rating"):
                t.rating = entry["rating"]
            if entry.get("trailer"):
                t.trailer_url = entry["trailer"]

    @synchronized
    def clear_override(self, name: str, fields: Optional[List[str]] = None) -> None:
        key = title_key(name)
        if key not in self.overrides:
            return
        if fields:
            for f in fields:
                self.overrides[key].pop(f, None)
            if not self.overrides[key]:
                self.overrides.pop(key)
        else:
            self.overrides.pop(key)
        _save_json(self.overrides_path, self.overrides)
        self.reload()

    @synchronized
    def forget_enrichment(self, name: str) -> None:
        key = title_key(name)
        self.enriched.pop(key, None)
        _save_json(self.enriched_path, self.enriched)
        self.reload()

    @synchronized
    def repair_trailer(self, name: str, replacement: Optional[str]) -> None:
        """Drop a dead trailer link from the sidecars; optionally store a good one.

        The link can live in two places — data/enriched.json (TMDB) and
        data/overrides.json (hand-edited) — and both must be cleaned so the
        dead URL cannot come back on the next reload.
        """
        key = title_key(name)
        changed = False

        override = self.overrides.get(key)
        if override and override.get("trailer"):
            override.pop("trailer", None)
            if not override:
                self.overrides.pop(key)
            changed = True

        enriched = self.enriched.get(key)
        if enriched and enriched.get("trailer_url"):
            enriched["trailer_url"] = replacement
            changed = True
        elif replacement:
            self.enriched[key] = {"trailer_url": replacement}
            changed = True

        if changed:
            _save_json(self.overrides_path, self.overrides)
            _save_json(self.enriched_path, self.enriched)
        title = self.find_by_name(name)
        if title is not None:
            title.trailer_url = replacement

    # -- lookup -----------------------------------------------------------
    def get(self, title_id: str) -> Optional[Title]:
        return self.library.get(title_id)

    def find_by_name(self, name: str) -> Optional[Title]:
        key = title_key(name)
        for t in self.library.titles:
            if title_key(t.name) == key:
                return t
        hits = self.library.find(name, limit=1)
        return hits[0] if hits else None

    def duplicates(self, cutoff: float = 0.9) -> List[dict]:
        return duplicate_candidates(self.library.titles, cutoff=cutoff)

    @synchronized
    def merge(self, keep_id: str, merge_id: str) -> None:
        keep, other = self.get(keep_id), self.get(merge_id)
        if keep is None or other is None:
            raise KeyError("Unknown title id")
        rules = self.config.get("merge_rules") or {}
        rules[other.name] = keep.name
        self.config["merge_rules"] = rules
        self.config.save()
        self.reload()

    def stats(self) -> dict:
        s = self.library.stats()
        s["enriched"] = sum(1 for t in self.library.titles if t.enriched)
        s["overridden"] = len(self.overrides)
        return s

