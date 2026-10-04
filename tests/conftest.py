"""Shared fixtures and synthetic catalog rows for the Caption Studio tests."""
from __future__ import annotations

import csv
import os

import pytest

from caption_studio.config import Config
from caption_studio.models import Title

# Columns the loader and fold logic read.  A hand-made catalog only needs a
# subset, but writing all of them keeps the fixtures close to real scans.
CSV_FIELDS = [
    "full_path", "file_name", "media_type", "title", "series_title",
    "season_number", "episode_number", "release_year", "duration_seconds",
    "size_bytes", "resolution_label", "audio_languages", "subtitle_languages",
    "drive_label", "directory_path", "quality_score", "issue_codes",
    "last_seen_utc",
]

BASE_ROW = {
    "full_path": "", "file_name": "", "media_type": "", "title": "",
    "series_title": "", "season_number": "", "episode_number": "",
    "release_year": "", "duration_seconds": "", "size_bytes": "",
    "resolution_label": "", "audio_languages": "", "subtitle_languages": "",
    "drive_label": "", "directory_path": "", "quality_score": "",
    "issue_codes": "", "last_seen_utc": "2026-09-26T15:00:10",
}


def episode_row(series="Test Series", season=1, ep=1, drive="D:",
                genre="Crime-Drama", year=2017, seen=None):
    fname = f"{series} S{season:02d}E{ep:02d}.mkv"
    row = dict(BASE_ROW)
    row.update({
        "full_path": f"{drive}\\TV\\{series} S{season:02d}\\{fname}",
        "file_name": fname,
        "media_type": "episode",
        "title": f"Episode {ep:02d}",
        "series_title": series,
        "season_number": str(season),
        "episode_number": str(ep),
        "release_year": str(year),
        "duration_seconds": "2520",          # 42 minutes
        "size_bytes": "1073741824",
        "resolution_label": "1080p",
        "audio_languages": "eng",
        "subtitle_languages": "eng",
        "drive_label": drive,
        "directory_path": f"{drive}\\TV\\{series} ({year} {genre})\\{series} S{season:02d}",
        "quality_score": "0.8",
    })
    if seen:
        row["last_seen_utc"] = seen
    return row


def movie_row(name="2 Guns", year=2013, drive="D:", genre="Action-Comedy",
              size=2147483648, res="1080p", seen=None):
    fname = f"{name} ({year}).mkv"
    row = dict(BASE_ROW)
    row.update({
        "full_path": f"{drive}\\Movies\\{fname}",
        "file_name": fname,
        "media_type": "movie",
        "title": f"{name} ({year})",
        "release_year": str(year),
        "duration_seconds": "6600",          # 110 minutes
        "size_bytes": str(size),
        "resolution_label": res,
        "audio_languages": "eng",
        "subtitle_languages": "eng|spa",
        "drive_label": drive,
        "directory_path": f"{drive}\\Movies\\{name} ({year} {genre})",
        "quality_score": "0.9",
    })
    if seen:
        row["last_seen_utc"] = seen
    return row


def write_catalog(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.fixture
def cfg(tmp_path):
    """A Config backed by a throwaway file, on top of the shipped defaults."""
    return Config({}, path=str(tmp_path / "config.json"))


@pytest.fixture
def movie():
    """A movie with every enrichment field filled — no caption warnings."""
    return Title(
        id="m00001", kind="movie", name="Die Hard", year=1988, year_end=1988,
        genres=["Action"], runtime_min=131, resolutions=["720p", "1080p"],
        audio_languages=["English"], subtitle_languages=["English"],
        overview=("A New York cop takes on terrorists in an LA skyscraper. "
                  "He is alone, and it is Christmas."),
        cast=["Bruce Willis"], rating="R", trailer_url="https://youtu.be/abc",
        tagline="Twelve terrorists. One cop.",
    )


@pytest.fixture
def series():
    """A fully-enriched series."""
    return Title(
        id="s00001", kind="series", name="Blue Lights", year=2015, year_end=2019,
        genres=["Crime", "Drama"], seasons=3, episodes=24, runtime_min=45,
        resolutions=["1080p"], audio_languages=["English"],
        overview=("A rookie constable learns the job on the streets of Belfast. "
                  "Every shift is a test."),
        cast=["Siân Brooke"], rating="TV-MA", trailer_url="https://youtu.be/def",
        tagline="The job breaks you in fast.",
    )

