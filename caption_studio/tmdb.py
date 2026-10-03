"""Optional TMDB enrichment.

Everything in this module is optional: with no API key the studio still works,
it just writes copy from the genre playbooks instead of real metadata.

Get a free key at https://www.themoviedb.org/settings/api and either set
``tmdb_api_key`` in config.json or pass ``--tmdb-key`` to the CLI.

Results are cached to ``.tmdb_cache/`` so repeat runs are instant and work
offline afterwards.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from .models import Title

BASE = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p/w500"
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".tmdb_cache")

# ISO 639-1 -> friendly name (only the ones that show up in practice)
_LANG = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian",
    "pt": "Portuguese", "ja": "Japanese", "ko": "Korean", "zh": "Chinese", "hi": "Hindi",
    "ar": "Arabic", "ru": "Russian", "tr": "Turkish", "zu": "Zulu", "no": "Norwegian",
    "sv": "Swedish", "da": "Danish", "nl": "Dutch", "pl": "Polish", "th": "Thai",
}


class TMDBError(RuntimeError):
    pass


class TMDBClient:
    def __init__(self, api_key: str, language: str = "en-US", cache_dir: str = CACHE_DIR,
                 timeout: int = 20):
        if not api_key:
            raise TMDBError("No TMDB API key configured.")
        self.api_key = api_key
        self.language = language
        self.cache_dir = cache_dir
        self.timeout = timeout
        os.makedirs(cache_dir, exist_ok=True)

    # -- plumbing ---------------------------------------------------------
    def _cache_path(self, key: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", key)[:180]
        return os.path.join(self.cache_dir, f"{safe}.json")

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None,
             cache_key: Optional[str] = None, ttl_days: int = 30) -> Dict[str, Any]:
        params = dict(params or {})
        params["api_key"] = self.api_key
        params.setdefault("language", self.language)
        key = cache_key or (path.strip("/").replace("/", "_") + "_" +
                            urllib.parse.urlencode(sorted(params.items())))
        cpath = self._cache_path(key)
        if os.path.exists(cpath):
            age = time.time() - os.path.getmtime(cpath)
            if age < ttl_days * 86400:
                try:
                    with open(cpath, "r", encoding="utf-8") as fh:
                        return json.load(fh)
                except Exception:
                    pass
        url = f"{BASE}{path}?" + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # network down, bad key, rate limit...
            raise TMDBError(f"TMDB request failed: {exc}") from exc
        try:
            with open(cpath, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
        except Exception:
            pass
        return data

    # -- search -----------------------------------------------------------
    def find(self, title: Title) -> Optional[Dict[str, Any]]:
        kind = "tv" if title.is_series else "movie"
        results = self.search(kind, title.name, title.year)
        if not results:
            # Retry with the year stripped from the name (e.g. "Blah (2026)").
            cleaned = re.sub(r"\s*\(\s*(19|20)\d{2}\s*\)\s*$", "", title.name).strip()
            if cleaned and cleaned != title.name:
                results = self.search(kind, cleaned, title.year)
        return results[0] if results else None

    def search(self, kind: str, query: str, year: Optional[int] = None) -> List[Dict[str, Any]]:
        params = {"query": query, "include_adult": "false"}
        if kind == "movie":
            if year:
                params["year"] = year
        else:
            if year:
                params["first_air_date_year"] = year
        data = self._get(f"/search/{kind}", params, cache_key=f"search_{kind}_{query}_{year}")
        results = data.get("results") or []
        if not results and year:
            params.pop("year", None)
            params.pop("first_air_date_year", None)
            data = self._get(f"/search/{kind}", params, cache_key=f"search_{kind}_{query}_noyear")
            results = data.get("results") or []
        return results

    # -- details ----------------------------------------------------------
    def _certification(self, kind: str, tmdb_id: int) -> Optional[str]:
        try:
            if kind == "movie":
                data = self._get(f"/movie/{tmdb_id}/release_dates")
                for country in data.get("results") or []:
                    if country.get("iso_3166_1") in ("US", "GB"):
                        for rel in country.get("release_dates") or []:
                            cert = (rel.get("certification") or "").strip()
                            if cert:
                                return cert
            else:
                data = self._get(f"/tv/{tmdb_id}/content_ratings")
                for country in data.get("results") or []:
                    if country.get("iso_3166_1") in ("US", "GB"):
                        rating = (country.get("rating") or "").strip()
                        if rating:
                            return rating
        except Exception:
            pass
        return None

    def _trailer(self, kind: str, tmdb_id: int) -> Optional[str]:
        try:
            data = self._get(f"/{kind}/{tmdb_id}/videos")
        except Exception:
            return None
        videos = [v for v in (data.get("results") or [])
                  if (v.get("site") or "").lower() == "youtube"]
        if not videos:
            return None
        preferred = [v for v in videos if (v.get("type") or "").lower() == "trailer"
                     and v.get("official")]
        for pool in (preferred, [v for v in videos if (v.get("type") or "").lower() == "trailer"],
                     videos):
            if pool:
                key = pool[0].get("key")
                if key:
                    return f"https://youtu.be/{key}"
        return None

    def _cast(self, kind: str, tmdb_id: int, limit: int = 6) -> List[str]:
        try:
            data = self._get(f"/{kind}/{tmdb_id}/credits")
        except Exception:
            return []
        cast = data.get("cast") or []
        names = [c.get("name", "").strip() for c in cast if c.get("name")]
        return [n for n in names if n][:limit]

    def enrich(self, title: Title, with_trailer: bool = True,
               match: Optional[int] = None) -> Dict[str, Any]:
        """Fill a Title with real metadata.  Returns a summary of what changed."""
        kind = "tv" if title.is_series else "movie"
        hit = None
        if match:
            hit = {"id": int(match)}
        else:
            hit = self.find(title)
        if not hit:
            raise TMDBError(f"No TMDB match for {title.name!r}")

        tmdb_id = int(hit["id"])
        details = self._get(f"/{kind}/{tmdb_id}")
        title.tmdb_id = tmdb_id

        changed = []
        overview = (details.get("overview") or "").strip()
        if overview:
            title.overview = overview
            changed.append("synopsis")
        tagline = (details.get("tagline") or "").strip()
        if tagline:
            title.tagline = tagline
            changed.append("tagline")

        if kind == "tv":
            first = (details.get("first_air_date") or "")[:4]
            last = (details.get("last_air_date") or "")[:4]
            status = details.get("status") or ""
            if first and first.isdigit():
                title.year = int(first)
                changed.append("year")
            if last and last.isdigit() and status != "Ended":
                title.year_end = int(last)
            elif last and last.isdigit():
                title.year_end = int(last)
            seasons = details.get("number_of_seasons")
            episodes = details.get("number_of_episodes")
            if seasons:
                title.seasons = int(seasons)
                changed.append("seasons")
            if episodes:
                title.episodes = int(episodes)
                changed.append("episodes")
            runtimes = details.get("episode_run_time") or []
            if runtimes:
                title.runtime_min = int(runtimes[0])
                changed.append("runtime")
        else:
            date = (details.get("release_date") or "")[:4]
            if date and date.isdigit():
                title.year = int(date)
                title.year_end = int(date)
                changed.append("year")
            runtime = details.get("runtime")
            if runtime:
                title.runtime_min = int(runtime)
                changed.append("runtime")

        genres = [g.get("name") for g in (details.get("genres") or []) if g.get("name")]
        if genres:
            merged = list(genres)
            for g in title.genres:
                if g not in merged:
                    merged.append(g)
            title.genres = merged[:3]
            changed.append("genres")

        poster = details.get("poster_path")
        if poster:
            title.poster_url = IMG + poster

        cast = self._cast(kind, tmdb_id, limit=6)
        if cast:
            title.cast = cast
            changed.append("cast")

        cert = self._certification(kind, tmdb_id)
        if cert:
            title.rating = cert
            changed.append("rating")

        spoken = details.get("spoken_languages") or []
        langs = [_LANG.get((s.get("iso_639_1") or "").lower(), s.get("name"))
                 for s in spoken]
        langs = [x for x in langs if x]
        if langs:
            title.audio_languages = langs[:3]
            changed.append("languages")

        if with_trailer:
            url = self._trailer(kind, tmdb_id)
            if url:
                title.trailer_url = url
                changed.append("trailer")

        title.enriched = True
        return {"title": title.name, "tmdb_id": tmdb_id,
                "matched": hit.get("name") or hit.get("title"),
                "changed": changed}
