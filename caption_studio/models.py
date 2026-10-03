"""Data model shared by the CLI, the web app and the exporters."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Title:
    """One sellable item in the library — a movie or a complete series."""

    id: str
    kind: str                       # "movie" | "series"
    name: str
    year: Optional[int] = None
    year_end: Optional[int] = None
    genres: List[str] = field(default_factory=list)
    seasons: int = 0
    episodes: int = 0
    runtime_min: int = 0
    total_bytes: int = 0
    resolutions: List[str] = field(default_factory=list)
    audio_languages: List[str] = field(default_factory=list)
    subtitle_languages: List[str] = field(default_factory=list)
    drives: List[str] = field(default_factory=list)
    folders: List[str] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    quality_score: float = 0.0
    issue_codes: List[str] = field(default_factory=list)

    # --- enrichment (filled by TMDB or by hand) --------------------------
    overview: Optional[str] = None
    tagline: Optional[str] = None
    cast: List[str] = field(default_factory=list)
    rating: Optional[str] = None
    trailer_url: Optional[str] = None
    poster_url: Optional[str] = None
    tmdb_id: Optional[int] = None
    enriched: bool = False

    # --- per-title overrides ----------------------------------------------
    dm_keyword: Optional[str] = None

    # ------------------------------------------------------------------
    @property
    def is_series(self) -> bool:
        return self.kind == "series"

    @property
    def year_label(self) -> str:
        if not self.year:
            return "—"
        if self.year_end and self.year_end != self.year:
            return f"{self.year}-{self.year_end}"
        return str(self.year)

    @property
    def size_gb(self) -> float:
        return round(self.total_bytes / (1024 ** 3), 2)

    @property
    def size_label(self) -> str:
        gb = self.size_gb
        if gb >= 1:
            return f"{gb:.1f} GB"
        return f"{max(1, round(self.total_bytes / (1024 ** 2)))} MB"

    @property
    def resolution_label(self) -> str:
        return " / ".join(self.resolutions) if self.resolutions else ""

    @property
    def kind_label(self) -> str:
        return "Series" if self.is_series else "Movie"

    @property
    def search_blob(self) -> str:
        return " ".join(
            [self.name, str(self.year or ""), " ".join(self.genres), self.kind_label]
        ).lower()

    @property
    def missing(self) -> List[str]:
        """Fields the caption needs but the catalog cannot supply."""
        gaps = []
        if not self.overview:
            gaps.append("synopsis")
        if not self.cast:
            gaps.append("cast")
        if not self.rating:
            gaps.append("rating")
        if not self.trailer_url:
            gaps.append("trailer")
        if not self.genres:
            gaps.append("genres")
        return gaps

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["year_label"] = self.year_label
        d["size_label"] = self.size_label
        d["size_gb"] = self.size_gb
        d["resolution_label"] = self.resolution_label
        d["kind_label"] = self.kind_label
        d["missing"] = self.missing
        d["is_series"] = self.is_series
        return d


# Resolution ordering used everywhere we list or compare qualities.
RESOLUTION_ORDER = {"360p": 1, "396p": 2, "400p": 3, "404p": 4, "432p": 5,
                    "480p": 6, "576p": 7, "720p": 8, "1080p": 9, "1440p": 10,
                    "2160p": 11, "4k": 11}


def sort_resolutions(values: List[str]) -> List[str]:
    seen = []
    for v in values:
        if v and v not in seen:
            seen.append(v)
    return sorted(seen, key=lambda v: (RESOLUTION_ORDER.get(v.lower(), 0), v))
