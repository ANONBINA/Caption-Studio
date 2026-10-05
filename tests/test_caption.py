"""Tests for caption assembly (caption_studio.caption)."""
from __future__ import annotations

from caption_studio.caption import CaptionOptions, build_caption, limit_report


def opts(cfg, **kw):
    return CaptionOptions.from_dict(kw, cfg)


def test_full_movie_layout(cfg, movie):
    cap = build_caption(movie, cfg, opts(cfg))
    lines = cap.text.split("\n")
    assert lines[0] == "🎬 Die Hard (1988)"
    assert "Action" in cap.text
    assert "📖 A New York cop takes on terrorists in an LA skyscraper." in cap.text
    assert "📅 1988 • 2h 11m" in cap.text
    assert "🌐 English" in cap.text
    assert "⭐ Bruce Willis" in cap.text
    assert "🔞 R" in cap.text
    assert "🎞️ Trailer: https://youtu.be/abc" in cap.text
    assert "✨ Twelve terrorists. One cop." in cap.text
    assert '📩 DM "DIE" for 720p / 1080p (flash or phone ready)' in cap.text
    assert "— Plugent 🍿" in cap.text
    assert cap.char_count == len(cap.text)
    assert cap.warnings == []


def test_full_series_specs(cfg, series):
    cap = build_caption(series, cfg, opts(cfg))
    assert "📅 2015-2019 • 3 Seasons • 24 Episodes (45 mins each)" in cap.text


def test_missing_synopsis_warns_and_uses_playbook(cfg, movie):
    movie.overview = None
    cap = build_caption(movie, cfg, opts(cfg))
    assert any("auto-written" in w for w in cap.warnings)
    hook = cap.sections["synopsis"]
    assert "Die Hard" in hook  # the playbook hook names the title


def test_synopsis_override_used_verbatim(cfg, movie):
    cap = build_caption(movie, cfg, opts(cfg, overrides={"synopsis": "Custom hook text."}))
    assert "📖 Custom hook text." in cap.text
    assert cap.warnings == []


def test_missing_fact_sections_warn(cfg, movie):
    movie.cast = []
    movie.rating = None
    movie.trailer_url = None
    cap = build_caption(movie, cfg, opts(cfg))
    joined = " ".join(cap.warnings)
    assert "cast" in joined and "rating" in joined and "trailer" in joined


def test_section_toggles_silence_warnings(cfg, movie):
    movie.cast = []
    movie.rating = None
    movie.trailer_url = None
    cap = build_caption(movie, cfg, opts(cfg, sections={"cast": False, "rating": False,
                                                        "trailer": False}))
    assert cap.warnings == []
    assert "⭐" not in cap.text and "🔞" not in cap.text and "🎞️" not in cap.text


def test_short_length_drops_sections(cfg, series):
    cap = build_caption(series, cfg, opts(cfg, length="short"))
    assert "🔍 Expect:" not in cap.text
    assert "💡 Why" not in cap.text
    assert "📩" in cap.text  # CTA survives


def test_teaser_drops_more(cfg, series):
    cap = build_caption(series, cfg, opts(cfg, length="teaser"))
    for marker in ("⭐", "🔞", "🎞️", "💡", "🔍 Expect:", "🌐"):
        assert marker not in cap.text
    assert "✨" in cap.text and "📩" in cap.text
    assert cap.warnings == []


def test_custom_brand_flows_through(cfg, movie):
    cfg.data["brand"] = "Acme"
    cfg.data["brand_footer_emoji"] = "🎬"
    cap = build_caption(movie, cfg, opts(cfg))
    assert "💡 Why Acme Recommends It:" in cap.text
    assert cap.text.endswith("— Acme 🎬")


def test_dm_keyword_override(cfg, movie):
    cap = build_caption(movie, cfg, opts(cfg, overrides={"dm_keyword": "HARD"}))
    assert '📩 DM "HARD" for' in cap.text


def test_hashtags_appended(cfg, movie):
    cfg.data["include_hashtags"] = True
    cap = build_caption(movie, cfg, opts(cfg))
    assert "#Plugent" in cap.hashtags
    assert "#movie" in cap.hashtags and "#1988" in cap.hashtags


def test_limit_report_flags_overflow(cfg, movie):
    cfg.data["limits"] = {"x": 10, "instagram": 100000}
    report = limit_report("x" * 50, cfg)
    by_platform = {r["platform"]: r for r in report}
    assert by_platform["x"]["fits"] is False
    assert by_platform["instagram"]["fits"] is True


def test_deterministic_output(cfg, movie):
    a = build_caption(movie, cfg, opts(cfg, variant=0)).text
    b = build_caption(movie, cfg, opts(cfg, variant=0)).text
    assert a == b

