"""Load the raw media-catalog CSVs and fold them into sellable titles.

The catalogs produced by the media scanner are *file level*: one row per video
file.  Captions are written per *title*, so episodes get folded up into their
series and each movie stands alone.

Everything is derived from data that already exists in the CSV:

* genre + year are encoded in folder names like
  ``2 Guns COMPLETE SINGLE (2013 Action-Comedy)``
* seasons / episodes / average runtime come from grouping episodes
* resolutions, languages and total size come from the file metadata
"""
from __future__ import annotations

import csv
import glob
import html as html_mod
import os
import re
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

from .models import Title, sort_resolutions

# Scanner-generated titles contain HTML entities, sometimes double-escaped
# ("Grey&#039;s Anatomy" arrives as "Grey&039;s Anatomy" — no hash, no amp).
_ENTITY_FIXES = ((re.compile(r"&0*39;", re.I), "'"),
                 (re.compile(r"&0*34;", re.I), '"'),
                 (re.compile(r"&amp(?!;|#)", re.I), "&"))


def unescape(text: str) -> str:
    out = text or ""
    for pattern, repl in _ENTITY_FIXES:
        out = pattern.sub(repl, out)
    # Two passes: "Grey&#039;s Anatomy" sometimes arrives as "&amp;#039;".
    return (html_mod.unescape(html_mod.unescape(out)) or "").strip()

# Names that are really episode labels, not movie titles.
GENERIC_EPISODE_RE = re.compile(
    r"^(episode|ep|part|chapter|movie)\s*[\W_]*\s*\d{1,3}\s*$", re.I)

# Noise words stripped from folder names when deriving a series title.
NAME_NOISE_RE = re.compile(
    r"\b(complete|c0mplete|conplete|coplete|coomplete|complet|single|full|"
    r"seasons?|series|orders?|requests?|pending|new|hd|hdr|x264|x265|"
    r"watch|wathc)\b", re.I)

# Require a separator before the season code so names like "Star Trek: DS9"
# keep their final "S9".
TRAILING_SEASON_RE = re.compile(
    r"(?:\s+|\s*[-–—]\s*)(?:s|season)\s*(\d{1,2})\s*$", re.I)

# Release/audio tags that leak into file names: "[1080p]", "[WEBRip]",
# "AAC5 1", "(YTS.MX)" ...
TAG_RE = re.compile(
    r"(\[[^\]]*\])|(\bAAC\s?\d[\s._]*\d\b)|(\b(?:DD|DTS|AC3|EAC3)\s?\d[\s._]*\d\b)|"
    r"(\b(?:WEBRip|WEB-?DL|BluRay|BRRip|HDRip|DVDRip|x264|x265|HEVC|10bit|"
    r"YTS(?:\.[A-Z]{2})?|YIFY|RARBG|GECKOS|NTb|FGT|AMZN|NF|DSNP)\b)|"
    r"(\b\d{3,4}p\b)", re.I)

# Columns that only exist in the real scanner output.  Catalogs missing them
# (hand-made samples, test fixtures) are skipped unless explicitly requested.
REQUIRED_COLUMNS = {"full_path", "media_type", "resolution_label", "directory_path"}

# ---------------------------------------------------------------------------
# Language helpers
# ---------------------------------------------------------------------------
LANG_NAMES = {
    "eng": "English", "en": "English", "english": "English",
    "und": "", "": "", "zul": "Zulu", "hin": "Hindi", "spa": "Spanish",
    "fre": "French", "fra": "French", "ger": "German", "deu": "German",
    "ita": "Italian", "jpn": "Japanese", "kor": "Korean", "por": "Portuguese",
    "ara": "Arabic", "chi": "Chinese", "zho": "Chinese", "rus": "Russian",
    "tur": "Turkish", "nob": "Norwegian", "nor": "Norwegian", "swe": "Swedish",
    "dan": "Danish", "dut": "Dutch", "nld": "Dutch", "pol": "Polish",
    "tha": "Thai", "vie": "Vietnamese", "heb": "Hebrew", "gre": "Greek",
    "ell": "Greek", "hrv": "Croatian", "hun": "Hungarian", "ind": "Indonesian",
    "may": "Malay", "msa": "Malay", "rum": "Romanian", "ron": "Romanian",
    "ukr": "Ukrainian", "cze": "Czech", "ces": "Czech", "fin": "Finnish",
    "fil": "Filipino", "mac": "Macedonian", "mkd": "Macedonian",
    "srp": "Serbian", "slv": "Slovenian", "bul": "Bulgarian",
}


def pretty_languages(raw: Iterable[str], limit: int = 3) -> List[str]:
    out: List[str] = []
    for chunk in raw:
        for code in [c.strip().lower() for c in re.split(r"[,/|;+]", chunk or "")]:
            name = LANG_NAMES.get(code, "")
            if not name:
                continue
            if name not in out:
                out.append(name)
    return out[:limit]


# ---------------------------------------------------------------------------
# Genre parsing
# ---------------------------------------------------------------------------
CANONICAL_GENRES = [
    "Action", "Adventure", "Animation", "Anime", "Biography", "Comedy",
    "Crime", "Documentary", "Drama", "Family", "Fantasy", "History",
    "Horror", "K-Drama", "Kids", "Music", "Musical", "Mystery", "Reality",
    "Romance", "Sci-Fi", "Sitcom", "Sport", "Superhero", "Thriller", "War",
    "Western",
]

# Free-text folder labels -> canonical genres.
GENRE_ALIASES = {
    "action": ["Action"], "action thriller": ["Action", "Thriller"],
    "action-thriller": ["Action", "Thriller"], "action comedy": ["Action", "Comedy"],
    "action-comedy": ["Action", "Comedy"], "action adventure": ["Action", "Adventure"],
    "action-adventure": ["Action", "Adventure"], "adventure": ["Adventure"],
    "animation": ["Animation"], "animated": ["Animation"], "anime": ["Anime"],
    "cartoon": ["Animation"], "comedy": ["Comedy"], "comedy-drama": ["Comedy", "Drama"],
    "comedy drama": ["Comedy", "Drama"], "comedy-romance": ["Comedy", "Romance"],
    "romcom": ["Comedy", "Romance"], "rom-com": ["Comedy", "Romance"],
    "crime": ["Crime"], "crime drama": ["Crime", "Drama"],
    "police procedural": ["Crime", "Drama"], "police": ["Crime", "Drama"],
    "detective": ["Crime", "Mystery"], "noir": ["Crime", "Thriller"],
    "documentary": ["Documentary"], "docu": ["Documentary"], "drama": ["Drama"],
    "american drama": ["Drama"], "dramedy": ["Comedy", "Drama"],
    "family": ["Family"], "family drama": ["Family", "Drama"],
    "fantasy": ["Fantasy"], "history": ["History"], "historical": ["History"],
    "horror": ["Horror"], "horror action": ["Horror", "Action"],
    "horror thriller": ["Horror", "Thriller"], "scary": ["Horror"],
    "k-drama": ["K-Drama", "Drama"], "kdrama": ["K-Drama", "Drama"],
    "korean drama": ["K-Drama", "Drama"], "kids": ["Kids"], "music": ["Music"],
    "musical": ["Musical"], "mystery": ["Mystery"], "mystery thriller": ["Mystery", "Thriller"],
    "reality": ["Reality"], "reality tv": ["Reality"], "romance": ["Romance"],
    "romantic": ["Romance"], "sci-fi": ["Sci-Fi"], "scifi": ["Sci-Fi"],
    "science fiction": ["Sci-Fi"], "sitcom": ["Sitcom"], "sit-com": ["Sitcom"],
    "comedy sitcom": ["Sitcom", "Comedy"], "sport": ["Sport"], "sports": ["Sport"],
    "superhero": ["Superhero", "Action"], "thriller": ["Thriller"],
    "thriller-action": ["Thriller", "Action"], "thriller drama": ["Thriller", "Drama"],
    "war": ["War"], "western": ["Western"], "biography": ["Biography"],
    "biopic": ["Biography"], "teen drama": ["Drama"], "soap": ["Drama"],
    "teledrama": ["Drama"], "nollywood": ["Drama"],
}

# Common typos seen in hand-typed folder names.
GENRE_TYPOFIX = {
    "theriller": "thriller", "thiller": "thriller", "triller": "thriller",
    "thrilier": "thriller", "romace": "romance", "romanace": "romance",
    "comdey": "comedy", "comedey": "comedy", "horor": "horror",
    "documetary": "documentary", "advenure": "adventure", "sciene fiction": "sci-fi",
    "drama ": "drama", "animaton": "animation", "famly": "family",
}

# Words that are part of the folder *name*, not a genre, even if they appear in
# the parenthesised suffix.
GENRE_STOPWORDS = {"complete", "c0mplete", "conplete", "copmlete", "coomplete",
                   "complet", "single", "full", "seasons", "season", "series",
                   "orders", "requests", "new", "hd", "hdr", "x264", "x265"}


def _clean_token(tok: str) -> str:
    tok = tok.strip().lower().strip(" .-–—_")
    return GENRE_TYPOFIX.get(tok, tok)


def parse_genres(text: str) -> List[str]:
    """Extract canonical genres from a folder / file name."""
    if not text:
        return []
    found: List[str] = []

    # 1) parenthesised suffix, e.g. "(2013 Action-Comedy)"
    for m in re.finditer(r"\(([^()]*)\)", text):
        inner = m.group(1)
        # Drop a leading year and quality tokens.
        inner = re.sub(r"\b(19|20)\d{2}\b", "", inner)
        inner = re.sub(r"\b\d{3,4}p\b", "", inner, flags=re.I)
        for part in re.split(r"[-/&,]", inner):
            tok = _clean_token(part)
            if not tok or tok in GENRE_STOPWORDS or tok.isdigit():
                continue
            if tok in GENRE_ALIASES:
                found.extend(GENRE_ALIASES[tok])
            elif len(tok) > 2:
                found.append(tok.title())

    # 2) folder-name hints, e.g. "...\\Animations\\..."
    low = text.lower()
    for hint, genres in (("animation", ["Animation"]), ("anime", ["Anime"]),
                         ("kids", ["Kids"]), ("cartoon", ["Animation"]),
                         ("nollywood", ["Drama"]), ("bollywood", ["Drama"]),
                         ("kdrama", ["K-Drama", "Drama"]), ("documentary", ["Documentary"])):
        if hint in low:
            found.extend(genres)

    # 3) split multi-word combos ("Action Drama", "Horror Comedy")
    expanded: List[str] = []
    for g in found:
        words = [w for w in re.split(r"[\s]+", g) if w]
        if len(words) > 1 and all(w.lower() in {c.lower() for c in CANONICAL_GENRES}
                                 for w in words):
            expanded.extend(w.title() for w in words)
        else:
            expanded.append(g)

    # 4) normalise: match against canonical list, keep first-seen order
    out: List[str] = []
    for g in expanded:
        g = g.strip()
        if not g:
            continue
        canon = None
        for c in CANONICAL_GENRES:
            if g.lower() == c.lower():
                canon = c
                break
        if canon is None:
            # fuzzy match for typos like "Thriler"
            import difflib
            close = difflib.get_close_matches(g, CANONICAL_GENRES, n=1, cutoff=0.86)
            canon = close[0] if close else g.title()
        if canon not in out:
            out.append(canon)
    return out


YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


def parse_year(text: str) -> Optional[int]:
    if not text:
        return None
    m = YEAR_RE.search(text)
    return int(m.group(1)) if m else None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


# ---------------------------------------------------------------------------
# Catalog loading
# ---------------------------------------------------------------------------
def _read_csv(path: str) -> Tuple[List[dict], List[str]]:
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []
        rows = [r for r in reader if r and any((v or "").strip() for v in r.values())]
    return rows, fields


def _int(value: str, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class Library:
    """The merged, de-duplicated, title-level view of every catalog file."""

    def __init__(self, titles: List[Title], sources: List[str]):
        self.titles = titles
        self.sources = sources
        self._by_id = {t.id: t for t in titles}

    # -- construction ----------------------------------------------------
    @classmethod
    def load(cls, patterns: Iterable[str], merge_rules: Optional[Dict[str, str]] = None,
             min_rows: int = 50, strip_prefixes: Optional[List[str]] = None) -> "Library":
        paths: List[str] = []
        for pattern in patterns:
            paths.extend(sorted(glob.glob(pattern)))
        paths = sorted(set(paths))

        # Newest catalog wins: keep the last record seen for each file path.
        files: Dict[str, dict] = {}
        sources: List[str] = []
        for path in paths:
            rows, fields = _read_csv(path)
            if len(rows) < min_rows or not REQUIRED_COLUMNS.issubset(set(fields)):
                continue
            sources.append(os.path.basename(path))
            for row in rows:
                key = (row.get("full_path") or row.get("file_name") or "").strip().lower()
                if not key:
                    continue
                prev = files.get(key)
                if prev is None or (row.get("last_seen_utc") or "") >= (prev.get("last_seen_utc") or ""):
                    files[key] = row

        titles = cls._fold(files.values(), merge_rules or {}, strip_prefixes or [])
        titles.sort(key=lambda t: (t.name.lower()))
        return cls(titles, sources)

    @staticmethod
    def _fold(rows: Iterable[dict], merge_rules: Dict[str, str],
              strip_prefixes: List[str]) -> List[Title]:
        movies: Dict[str, Title] = {}
        series: Dict[str, _SeriesAccumulator] = {}

        for row in rows:
            media_type = (row.get("media_type") or "").strip().lower()
            name = clean_title(row.get("series_title") or row.get("title") or "")
            if media_type == "movie" and not GENERIC_EPISODE_RE.match(name):
                _add_movie(movies, row)
                continue
            # Either a real episode row, or a movie row whose title is just
            # "Episode 07" — in both cases it belongs to a series.
            if not name or GENERIC_EPISODE_RE.match(name):
                derived, derived_season = series_name_from_folder(
                    row.get("directory_path") or "")
                if not derived:
                    if name:
                        _add_movie(movies, row)
                    continue
                name = derived
                if not (row.get("season_number") or "").strip() and derived_season:
                    row = dict(row)
                    row["season_number"] = str(derived_season)
                if not (row.get("series_title") or "").strip():
                    row = dict(row)
                    row["series_title"] = derived
            name = _strip_prefix(name, strip_prefixes)
            name = merge_rules.get(name, name)
            key = _slug(name) or name.lower()
            acc = series.get(key)
            if acc is None:
                acc = series[key] = _SeriesAccumulator(name)
            acc.add(row, merge_rules)

        titles: List[Title] = list(movies.values())
        titles.extend(acc.build() for acc in series.values())

        # Re-apply merge rules now that slugs exist (catches case differences).
        if merge_rules or strip_prefixes:
            merged: Dict[str, Title] = {}
            for t in titles:
                target = _strip_prefix(merge_rules.get(t.name, t.name), strip_prefixes)
                key = _slug(target)
                if key in merged:
                    merged[key] = _merge_titles(merged[key], t)
                else:
                    t.name = target
                    merged[key] = t
            titles = list(merged.values())

        for idx, t in enumerate(titles):
            if not t.id:
                t.id = f"t{idx:05d}"
        return titles

    # -- lookup -----------------------------------------------------------
    def get(self, title_id: str) -> Optional[Title]:
        return self._by_id.get(title_id)

    def find(self, query: str, limit: int = 20) -> List[Title]:
        q = _slug(query)
        if not q:
            return self.titles[:limit]
        scored = []
        for t in self.titles:
            name = _slug(t.name)
            if not name:
                continue
            if name == q:
                score = 0
            elif name.startswith(q):
                score = 1
            elif q in name:
                score = 2
            elif q in _slug(" ".join(t.genres)):
                score = 4
            else:
                continue
            scored.append((score, t.year or 0, t.name.lower(), t))
        scored.sort(key=lambda x: (x[0], -x[1], x[2]))
        return [s[3] for s in scored[:limit]]

    def search(self, query: str = "", kind: str = "", genre: str = "",
               resolution: str = "", limit: int = 100, offset: int = 0) -> Tuple[List[Title], int]:
        results = self.titles
        if query.strip():
            q = _slug(query)
            results = [t for t in results if q in _slug(t.name)]
        if kind:
            results = [t for t in results if t.kind == kind]
        if genre:
            g = genre.lower()
            results = [t for t in results if any(x.lower() == g for x in t.genres)]
        if resolution:
            r = resolution.lower()
            results = [t for t in results if r in [x.lower() for x in t.resolutions]]
        return results[offset:offset + limit], len(results)

    def all_genres(self) -> List[Tuple[str, int]]:
        counts: Dict[str, int] = defaultdict(int)
        for t in self.titles:
            for g in t.genres:
                counts[g] += 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    def stats(self) -> dict:
        movies = [t for t in self.titles if t.kind == "movie"]
        series = [t for t in self.titles if t.kind == "series"]
        return {
            "titles": len(self.titles),
            "movies": len(movies),
            "series": len(series),
            "episodes": sum(t.episodes for t in series),
            "seasons": sum(t.seasons for t in series),
            "hours": round(sum(t.runtime_min * max(t.episodes, 1) for t in self.titles) / 60),
            "total_gb": round(sum(t.total_bytes for t in self.titles) / (1024 ** 3), 1),
            "sources": self.sources,
            "genres": self.all_genres()[:12],
            "enriched": sum(1 for t in self.titles if t.enriched),
        }


class _SeriesAccumulator:
    def __init__(self, name: str):
        self.name = name
        self.rows: List[dict] = []

    def add(self, row: dict, merge_rules: Dict[str, str]) -> None:
        self.rows.append(row)

    def build(self) -> Title:
        rows = self.rows
        seasons = {_int(r.get("season_number")) for r in rows if (r.get("season_number") or "").strip()}
        seasons.discard(0)
        # Count each episode once even when duplicate copies sit on two drives.
        numbered = [r for r in rows if (r.get("episode_number") or "").strip()]
        unnumbered = [r for r in rows if not (r.get("episode_number") or "").strip()]
        episodes = len({(r.get("season_number"), r.get("episode_number")) for r in numbered}) \
            + len(unnumbered)

        durations = [_float(r.get("duration_seconds")) for r in rows]
        durations = [d for d in durations if d > 60]
        avg = sum(durations) / len(durations) / 60 if durations else 0

        years = [int(_int(r.get("release_year"))) for r in rows if _int(r.get("release_year"))]
        # Ignore nonsense years when picking the start year.
        years = [y for y in years if 1950 <= y <= 2035]
        year = min(years) if years else parse_year(rows[0].get("directory_path", ""))
        year_end = max(years) if years else year

        # Prefer the folder names (they hold the genre suffix).
        genre_source = " ".join((r.get("directory_path") or "") for r in rows[:40])
        genres = parse_genres(genre_source)
        if not genres:
            genres = parse_genres(" ".join(r.get("file_name") or "" for r in rows[:40]))

        resolutions = sort_resolutions([(r.get("resolution_label") or "").strip() for r in rows])
        paths = sorted({(r.get("directory_path") or "").strip() for r in rows if r.get("directory_path")})
        files = [(r.get("full_path") or "").strip() for r in rows]

        return Title(
            id="",
            kind="series",
            name=_clean_display(self.name),
            year=year,
            year_end=year_end,
            genres=genres[:3],
            seasons=len(seasons) or 1,
            episodes=episodes,
            runtime_min=int(round(avg)) if avg else 0,
            total_bytes=sum(_int(r.get("size_bytes")) for r in rows),
            resolutions=resolutions,
            audio_languages=pretty_languages(r.get("audio_languages") for r in rows),
            subtitle_languages=pretty_languages(r.get("subtitle_languages") for r in rows),
            drives=sorted({(r.get("drive_label") or "").strip() for r in rows if r.get("drive_label")}),
            folders=paths[:8],
            files=files[:5],
            quality_score=round(sum(_float(r.get("quality_score")) for r in rows) / max(len(rows), 1), 1),
            issue_codes=sorted({c for r in rows for c in (r.get("issue_codes") or "").split("|") if c}),
        )


def clean_title(name: str) -> str:
    """Tidy a scanner title.

    'Agent Kim Reactivated (2026)'      -> 'Agent Kim Reactivated'
    'Apex AAC5 1'                       -> 'Apex'
    'Beauty In Black S01'               -> 'Beauty In Black'
    'Code 8 (2019) [BluRay] [1080p]'    -> 'Code 8'
    'S.W.A.T.' stays intact.
    """
    out = unescape(name)
    out = TAG_RE.sub(" ", out)
    out = re.sub(r"\s*\(\s*(19|20)\d{2}\s*\)\s*$", "", out)
    out = re.sub(r"\s+\b(19|20)\d{2}\s*$", "", out)
    out = TRAILING_SEASON_RE.sub("", out)
    out = out.replace("_", " ")
    # "Beauty.In.Black" -> "Beauty In Black", but leave "S.W.A.T." alone.
    if " " not in out.strip() and out.count(".") >= 2:
        out = out.replace(".", " ")
    out = re.sub(r"\s{2,}", " ", out).strip(" -–—:,")
    return out


def _clean_display(name: str) -> str:
    """Backwards-compatible wrapper around :func:`clean_title`."""
    return clean_title(name)


def _strip_prefix(name: str, prefixes: Iterable[str]) -> str:
    """Drop seller prefixes like 'Watch ' so 'Watch 24' folds into '24'."""
    out = name or ""
    changed = True
    while changed:
        changed = False
        for prefix in prefixes or []:
            if prefix and out.lower().startswith(prefix.lower()):
                out = out[len(prefix):].strip(" -–—")
                changed = True
    return out or name


def series_name_from_folder(path: str) -> Tuple[str, Optional[int]]:
    """Derive a series title (and season) from a folder such as 'Mindhunter S01'."""
    parts = [p for p in re.split(r"[\\/]", path or "") if p.strip()]
    if not parts:
        return "", None
    leaf = unescape(parts[-1])
    season = None
    m = TRAILING_SEASON_RE.search(leaf)
    if m:
        season = int(m.group(1))
        leaf = leaf[:m.start()]
    leaf = re.sub(r"\((?:19|20)\d{2}[^)]*\)", "", leaf)
    leaf = NAME_NOISE_RE.sub(" ", leaf)
    leaf = re.sub(r"\s*[-–—]\s*$", "", leaf).strip()
    leaf = re.sub(r"\s{2,}", " ", leaf).strip(" -–—._")
    if not leaf and len(parts) > 1:
        return series_name_from_folder("\\".join(parts[:-1]))
    return leaf, season


def _add_movie(movies: Dict[str, Title], row: dict) -> None:
    raw_name = (row.get("title") or "").strip()
    name = _clean_display(raw_name)
    if not name:
        name = _clean_display((row.get("file_name") or "").rsplit(".", 1)[0])
    directory = (row.get("directory_path") or "").strip()
    filename = (row.get("file_name") or "").strip()
    year = _int(row.get("release_year")) or parse_year(directory) or parse_year(filename)
    if year and not (1950 <= year <= 2035):
        year = None
    # Same title + different year = different film, so the year is part of the key.
    key = f"{_slug(name)}#{year or 'na'}" or _slug(raw_name)
    if not key.strip("#"):
        return

    genres = parse_genres(directory) or parse_genres(filename)
    runtime = int(round(_float(row.get("duration_seconds")) / 60))
    if runtime > 400:      # clearly a mis-probe
        runtime = 0

    existing = movies.get(key)
    candidate = Title(
        id="",
        kind="movie",
        name=name,
        year=year,
        year_end=year,
        genres=genres[:3],
        seasons=0,
        episodes=1,
        runtime_min=runtime,
        total_bytes=_int(row.get("size_bytes")),
        resolutions=sort_resolutions([(row.get("resolution_label") or "").strip()]),
        audio_languages=pretty_languages([row.get("audio_languages")]),
        subtitle_languages=pretty_languages([row.get("subtitle_languages")]),
        drives=[(row.get("drive_label") or "").strip()] if row.get("drive_label") else [],
        folders=[directory] if directory else [],
        files=[(row.get("full_path") or "").strip()],
        quality_score=_float(row.get("quality_score")),
        issue_codes=[c for c in (row.get("issue_codes") or "").split("|") if c],
    )
    if existing is None:
        movies[key] = candidate
    else:
        movies[key] = _merge_titles(existing, candidate)


def _merge_titles(a: Title, b: Title) -> Title:
    """Merge two entries that are really the same title (e.g. a typo variant)."""
    a.seasons = max(a.seasons, b.seasons)
    a.episodes = max(a.episodes, b.episodes)
    a.total_bytes += b.total_bytes
    a.files = (a.files + b.files)[:5]
    a.folders = sorted(set(a.folders + b.folders))[:8]
    a.drives = sorted(set(a.drives + b.drives))
    a.resolutions = sort_resolutions(a.resolutions + b.resolutions)
    for g in b.genres:
        if g not in a.genres:
            a.genres.append(g)
    a.genres = a.genres[:3]
    a.runtime_min = a.runtime_min or b.runtime_min
    a.year = min([y for y in (a.year, b.year) if y], default=None)
    a.year_end = max([y for y in (a.year_end, b.year_end) if y], default=None)
    for lang in b.audio_languages:
        if lang not in a.audio_languages:
            a.audio_languages.append(lang)
    for lang in b.subtitle_languages:
        if lang not in a.subtitle_languages:
            a.subtitle_languages.append(lang)
    return a


def duplicate_candidates(titles: List[Title], cutoff: float = 0.9, limit: int = 40):
    """Flag likely typos / variant spellings of the same title."""
    import difflib
    pairs = []
    for i, a in enumerate(titles):
        sa = _slug(a.name)
        for b in titles[i + 1:]:
            sb = _slug(b.name)
            if not sa or not sb:
                continue
            if sa == sb:
                continue
            ratio = difflib.SequenceMatcher(None, sa, sb).ratio()
            if ratio >= cutoff:
                pairs.append({"a": a.id, "b": b.id, "a_name": a.name, "b_name": b.name,
                              "score": round(ratio, 3)})
    pairs.sort(key=lambda p: -p["score"])
    return pairs[:limit]
