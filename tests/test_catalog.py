"""Tests for catalog loading, name repair and title folding."""
from __future__ import annotations

from caption_studio.catalog import (
    Library,
    _strip_prefix,
    clean_title,
    duplicate_candidates,
    parse_genres,
    parse_year,
    series_name_from_folder,
    unescape,
)
from tests.conftest import episode_row, movie_row


# -- name repair --------------------------------------------------------------
def test_unescape_html_entities():
    assert unescape("Grey&039;s Anatomy") == "Grey's Anatomy"
    assert unescape("Grey&#039;s Anatomy") == "Grey's Anatomy"
    assert unescape("Ben &amp; Holly") == "Ben & Holly"


def test_clean_title_docstring_examples():
    assert clean_title("Agent Kim Reactivated (2026)") == "Agent Kim Reactivated"
    assert clean_title("Apex AAC5 1") == "Apex"
    assert clean_title("Beauty In Black S01") == "Beauty In Black"
    assert clean_title("Code 8 (2019) [BluRay] [1080p]") == "Code 8"


def test_parse_year():
    assert parse_year("Show (2013 Action)") == 2013
    assert parse_year("no year here") is None
    assert parse_year("") is None


def test_parse_genres_parenthesised():
    assert parse_genres("2 Guns COMPLETE SINGLE (2013 Action-Comedy)") == ["Action", "Comedy"]


def test_parse_genres_fixes_typos():
    assert parse_genres("Show (2013 Theriller)") == ["Thriller"]
    assert parse_genres("Movie (2019 Comdey)") == ["Comedy"]


def test_strip_prefixes():
    assert _strip_prefix("Watch 24", ["Watch "]) == "24"
    assert _strip_prefix("Wathc 24", ["Watch ", "Wathc "]) == "24"
    assert _strip_prefix("24", ["Watch "]) == "24"


def test_series_name_from_folder():
    assert series_name_from_folder("D:\\TV\\Mindhunter S01") == ("Mindhunter", 1)
    name, season = series_name_from_folder("D:\\TV\\Show (2019 Comedy)\\Show S02")
    assert name == "Show" and season == 2


# -- folding ------------------------------------------------------------------
def test_movie_copies_on_two_drives_merge(movie_rows=None):
    rows = [
        movie_row(name="2 Guns", drive="D:", size=100, res="1080p"),
        movie_row(name="2 Guns", drive="E:", size=50, res="720p"),
    ]
    titles = Library._fold(rows, {}, [])
    assert len(titles) == 1
    t = titles[0]
    assert t.name == "2 Guns" and t.year == 2013
    assert t.total_bytes == 150
    assert t.resolutions == ["720p", "1080p"]
    assert sorted(t.drives) == ["D:", "E:"]


def test_episode_rows_fold_into_one_series():
    rows = [episode_row(season=s, ep=e) for s in (1, 2) for e in range(1, 21)]
    titles = Library._fold(rows, {}, [])
    assert len(titles) == 1
    t = titles[0]
    assert t.kind == "series" and t.name == "Test Series"
    assert t.seasons == 2 and t.episodes == 40
    assert t.runtime_min == 42
    assert t.genres == ["Crime", "Drama"]


def test_duplicate_episode_copies_counted_once():
    rows = [episode_row(season=1, ep=e) for e in range(1, 11)]
    rows.append(episode_row(season=1, ep=1, drive="E:"))  # same ep, second drive
    titles = Library._fold(rows, {}, [])
    assert len(titles) == 1
    assert titles[0].episodes == 10
    assert sorted(titles[0].drives) == ["D:", "E:"]


def test_episode_filed_as_movie_gets_rehomed():
    rows = [episode_row(series="Detective Pine", season=1, ep=e) for e in range(1, 11)]
    # A movie row whose title is just "Episode 07" — the real name is the folder.
    stray = movie_row(name="Episode 07", drive="D:")
    stray["media_type"] = "movie"
    stray["title"] = "Episode 07"
    stray["series_title"] = ""
    stray["directory_path"] = "D:\\TV\\Detective Pine (2017 Crime-Drama)\\Detective Pine S01"
    stray["season_number"] = ""
    stray["episode_number"] = ""
    stray["release_year"] = "2017"
    stray["duration_seconds"] = "2520"
    rows.append(stray)
    titles = Library._fold(rows, {}, [])
    series = [t for t in titles if t.kind == "series"]
    movies = [t for t in titles if t.kind == "movie"]
    assert len(series) == 1 and not movies
    assert series[0].name == "Detective Pine"
    assert series[0].episodes == 11  # the stray joined as an unnumbered episode


def test_merge_rules_collapse_variants():
    why_a = episode_row(season=1, ep=1)
    why_a["series_title"] = "13 Reason Why"
    why_b = episode_row(season=1, ep=1)
    why_b["series_title"] = "13 Reasons Why"
    rows = [
        movie_row(name="2 Guns"),
        movie_row(name="2 Gunss", size=5),
        episode_row(season=1, ep=1),
        why_a,
        why_b,
    ]
    titles = Library._fold(rows, {"2 Gunss": "2 Guns"}, [])
    movies = sorted(t.name for t in titles if t.kind == "movie")
    series = sorted(t.name for t in titles if t.kind == "series")
    assert movies == ["2 Guns"]
    # No rule for the 13 Reason(s) Why pair yet — it needs the Duplicates tool.
    assert series == ["13 Reason Why", "13 Reasons Why", "Test Series"]


def test_ids_assigned():
    titles = Library._fold([movie_row(), movie_row(name="Other", year=2020)], {}, [])
    assert all(t.id.startswith("t") for t in titles)
    assert len({t.id for t in titles}) == 2


# -- search & duplicates --------------------------------------------------------
def _library():
    rows = [
        movie_row(name="2 Guns"), movie_row(name="Breaking Bad", genre="Crime"),
        episode_row(series="13 Reason Why"),
        episode_row(series="13 Reasons Why"),
    ]
    return Library._fold(rows, {}, [])


def test_search_filters():
    lib = Library(_library(), ["test.csv"])
    results, total = lib.search(query="guns")
    assert total == 1 and results[0].name == "2 Guns"
    results, _ = lib.search(kind="series")
    assert all(t.kind == "series" for t in results)


def test_find_scores_exact_match_first():
    lib = Library(_library(), ["test.csv"])
    hits = lib.find("2 Guns", limit=5)
    assert hits[0].name == "2 Guns"


def test_duplicate_candidates_flag_typos():
    titles = _library()
    pairs = duplicate_candidates(titles, cutoff=0.9)
    flagged = {(p["a_name"], p["b_name"]) for p in pairs}
    assert any("13 Reason" in a and "13 Reason" in b for a, b in flagged)
<<<<<<< HEAD
=======

>>>>>>> origin/master
