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
import urllib.error
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


# ---------------------------------------------------------------------------
# YouTube validation
# ---------------------------------------------------------------------------
# TMDB's video list goes stale: videos get deleted, made private or
# region-blocked.  oEmbed tells us for free (no API key) whether a video
# still exists: 200 = alive, 400/404 = gone.
YOUTUBE_OEMBED = "https://www.youtube.com/oembed"
YT_CHECK_TTL_DAYS = 30

# TMDB video types, best candidates for a promo link first.
_TYPE_RANK = {"trailer": 0, "teaser": 1, "clip": 2, "featurette": 3,
              "behind the scenes": 4, "opening credits": 5}


def youtube_video_id(url: Optional[str]) -> Optional[str]:
    """Pull the 11-char id out of any common YouTube URL (or a bare id).

    Returns None for non-YouTube links — those can't be checked here, so
    they are always accepted rather than dropped.
    """
    text = (url or "").strip()
    if not text:
        return None
    match = re.search(
        r"(?:youtu\.be/|youtube\.com/(?:watch\?(?:[^#]*&)?v=|embed/|shorts/|live/))"
        r"([A-Za-z0-9_-]{11})", text)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text
    return None


def youtube_ok(video: Optional[str], cache_dir: str = CACHE_DIR,
               ttl_days: int = YT_CHECK_TTL_DAYS, timeout: int = 8) -> bool:
    """True unless YouTube proves the video is gone.

    Unknown outcomes — network errors, rate limits, non-YouTube links — are
    treated as OK: we only ever drop a link we can *prove* is dead.  Results
    are cached in ``.tmdb_cache/yt_<id>.json`` so each link is checked once
    per TTL period.
    """
    vid = youtube_video_id(video)
    if not vid:
        return True
    os.makedirs(cache_dir, exist_ok=True)
    cpath = os.path.join(cache_dir, f"yt_{vid}.json")
    if os.path.exists(cpath):
        age = time.time() - os.path.getmtime(cpath)
        if age < ttl_days * 86400:
            try:
                with open(cpath, "r", encoding="utf-8") as fh:
                    return bool(json.load(fh).get("ok"))
            except Exception:
                pass
    query = urllib.parse.urlencode(
        {"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"})
    try:
        with urllib.request.urlopen(f"{YOUTUBE_OEMBED}?{query}", timeout=timeout) as resp:
            code = resp.status
    except urllib.error.HTTPError as exc:
        code = exc.code
    except Exception:
        # Timeout / offline / DNS — unknown, so accept without caching.
        return True
    ok = code not in (400, 404)      # 200 alive; 401/403 restricted but real
    try:
        with open(cpath, "w", encoding="utf-8") as fh:
            json.dump({"ok": ok, "checked": int(time.time())}, fh)
    except Exception:
        pass
    return ok


def rank_trailers(videos: Optional[List[Dict[str, Any]]],
                  language: str = "en-US") -> List[Dict[str, Any]]:
    """YouTube candidates worth trying, best first.

    Preference: trailer > teaser > clip > …, official over fan uploads, then
    the configured language over foreign ones (mirrors the old three-tier
    pick, but sorted instead of hard-coded pools).
    """
    lang = (language or "").split("-")[0].lower()
    yt = [v for v in (videos or [])
          if (v.get("site") or "").lower() == "youtube" and v.get("key")]

    def score(v: Dict[str, Any]):
        vtype = (v.get("type") or "other").strip().lower()
        official = 0 if v.get("official") else 1
        iso = (v.get("iso_639_1") or "").strip().lower()
        lang_penalty = 0 if (not lang or iso in (lang, "", "und")) else 1
        return (_TYPE_RANK.get(vtype, 6), official, lang_penalty)

    return sorted(yt, key=score)


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

    def _trailer(self, kind: str, tmdb_id: int, refresh: bool = False) -> Optional[str]:
        """A YouTube trailer that is ranked well *and* still exists."""
        try:
            data = self._get(f"/{kind}/{tmdb_id}/videos",
                             ttl_days=0 if refresh else 30)
        except Exception:
            if not refresh:
                return None
            try:
                data = self._get(f"/{kind}/{tmdb_id}/videos")  # fall back to cache
            except Exception:
                return None
        for candidate in rank_trailers(data.get("results") or [], self.language):
            if youtube_ok(candidate["key"], cache_dir=self.cache_dir):
                return f"https://youtu.be/{candidate['key']}"
        return None

    def trailer_for(self, title: Title, refresh: bool = False) -> Optional[str]:
        """Fresh, validated trailer URL for a title — None if nothing usable.

        Used by the repair flow: ``refresh=True`` bypasses the 30-day TMDB
        cache so deleted videos get a real chance at a replacement.
        """
        kind = "tv" if title.is_series else "movie"
        tmdb_id = title.tmdb_id
        if not tmdb_id:
            hit = self.find(title)
            if not hit:
                return None
            tmdb_id = int(hit["id"])
        return self._trailer(kind, tmdb_id, refresh=refresh)

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

