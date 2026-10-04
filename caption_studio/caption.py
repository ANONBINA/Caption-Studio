"""Assemble a finished promo caption from a Title + config.

The default output mirrors the reference post exactly:

    🎬 Malcolm in the Middle (2000)
    Comedy | Sitcom | Family

    📖 A boy genius navigates the chaos of a hilariously dysfunctional
    family—where survival means outsmarting everyone, especially his mom.

    🔍 Expect:
    ✅ Bryan Cranston before Breaking Bad
    ✅ Breaking the fourth wall
    ✅ Pure, unfiltered family mayhem
    ✅ A finale that still hits hard

    📅 2000-2006 • 7 Seasons • 151 Episodes (22 mins each)
    🌐 English
    ⭐ Frankie Muniz | Bryan Cranston | Jane Kaczmarek
    🔞 TV-PG

    💡 Why Plugent Recommends It:
    This is the sitcom that redefined family comedy...

    🎞️ Trailer: https://youtu.be/xxxx

    ✨ Dysfunctional, hilarious, and timeless.

    📩 DM "MALCOLM" for 720p / 1080p (flash or phone ready)

    — Plugent 🍿
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .config import Config
from .creative import (
    condense_overview,
    dm_keyword,
    make_expect_bullets,
    make_hook,
    make_tagline,
    make_why,
)
from .models import Title

DOT = " • "


@dataclass
class CaptionOptions:
    variant: int = 0
    style: str = "classic"        # classic | extended
    length: str = "full"          # full | short | teaser
    expect_count: int = 4
    sections: Dict[str, bool] = field(default_factory=dict)
    overrides: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any], cfg: Config) -> "CaptionOptions":
        data = data or {}
        opts = cls(
            variant=int(data.get("variant", 0) or 0),
            style=data.get("style") or cfg.get("default_style", "classic"),
            length=data.get("length") or cfg.get("default_length", "full"),
            expect_count=int(data.get("expect_count", 4) or 4),
            sections=dict(data.get("sections") or {}),
            overrides=dict(data.get("overrides") or {}),
        )
        if opts.length == "short":
            opts.sections.setdefault("why", False)
            opts.sections.setdefault("expect", False)
        elif opts.length == "teaser":
            for key in ("why", "expect", "cast", "trailer", "rating", "language"):
                opts.sections.setdefault(key, False)
        # The storage/size line is opt-in: it isn't part of the classic layout.
        opts.sections.setdefault(
            "storage", bool(cfg.get("include_storage_line", False)) or opts.style == "extended")
        opts.sections.setdefault("hashtags", bool(cfg.get("include_hashtags", False)))
        return opts


@dataclass
class Caption:
    text: str
    title_id: str
    title_name: str
    hashtags: str = ""
    warnings: List[str] = field(default_factory=list)
    char_count: int = 0
    sections: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "title_id": self.title_id,
            "title_name": self.title_name,
            "hashtags": self.hashtags,
            "warnings": self.warnings,
            "char_count": self.char_count,
            "sections": self.sections,
        }


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _ov(opts: CaptionOptions, key: str, default: bool = True) -> bool:
    return bool(opts.overrides.get(key, opts.sections.get(key, default)))


def _specs_line(title: Title, cfg: Config) -> str:
    icon = cfg.icon("specs")
    if title.is_series:
        parts = [title.year_label]
        if title.seasons:
            parts.append(f"{title.seasons} Season{'s' if title.seasons != 1 else ''}")
        if title.episodes:
            each = f" ({title.runtime_min} mins each)" if title.runtime_min else ""
            parts.append(f"{title.episodes} Episode{'s' if title.episodes != 1 else ''}{each}")
        return f"{icon} " + DOT.join(p for p in parts if p)

    parts = []
    if title.year:
        parts.append(str(title.year))
    if title.runtime_min:
        h, m = divmod(title.runtime_min, 60)
        parts.append(f"{h}h {m}m" if h else f"{m}m")
    return f"{icon} " + DOT.join(parts) if parts else ""


def _storage_line(title: Title, cfg: Config) -> str:
    icon = cfg.icon("storage")
    parts = [title.size_label]
    if title.resolutions:
        parts.append(" / ".join(title.resolutions))
    if title.subtitle_languages:
        parts.append(f"Subs: {', '.join(title.subtitle_languages[:2])}")
    return f"{icon} " + DOT.join(parts)


def _hashtags(title: Title, cfg: Config) -> str:
    template = cfg.get("hashtag_template", "\n#{brand_clean} #{kind} #{genre_clean} #{year}")
    brand_clean = "".join(ch for ch in cfg.brand if ch.isalnum())
    genre_clean = "".join(ch for ch in (title.genres[0] if title.genres else "video")
                          if ch.isalnum())
    return template.format(
        brand=cfg.brand, brand_clean=brand_clean, kind=title.kind_label.lower(),
        genre=title.genres[0] if title.genres else "video", genre_clean=genre_clean,
        year=title.year or "", title=title.name,
    )


def _resolutions_phrase(title: Title, cfg: Config) -> str:
    if title.resolutions:
        return " / ".join(title.resolutions)
    return cfg.get("cta_fallback_resolution", "720p / 1080p")


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------
def build_caption(title: Title, cfg: Config, options: Optional[CaptionOptions] = None) -> Caption:
    opts = options or CaptionOptions.from_dict({}, cfg)
    warnings: List[str] = []
    sections: Dict[str, str] = {}

    ov = dict(opts.overrides)
    hook_override = (ov.get("synopsis") or "").strip()
    tagline_override = (ov.get("tagline") or "").strip()
    why_override = (ov.get("why") or "").strip()
    keyword_override = (ov.get("dm_keyword") or "").strip()

    # --- header ---------------------------------------------------------
    title_icon = cfg.icon("title_series") if title.is_series else cfg.icon("title_movie")
    header_year = f" ({title.year})" if title.year else ""
    head = f"{title_icon} {title.name}{header_year}"
    block = [head]

    # --- genres ---------------------------------------------------------
    if _ov(opts, "genres") and title.genres:
        limit = int(cfg.get("max_genres", 3) or 3)
        block.append(" | ".join(title.genres[:limit]))
    elif _ov(opts, "genres"):
        warnings.append("No genre in the catalog — add one, or the genre line is skipped.")

    # --- synopsis / hook --------------------------------------------------
    if _ov(opts, "synopsis"):
        if hook_override:
            hook = hook_override
        elif title.overview:
            hook = condense_overview(title.overview)
        else:
            hook = make_hook(title, opts.variant)
            warnings.append(
                "Synopsis is auto-written from the genre playbook — replace it with the real "
                "logline (or add a TMDB key) before posting.")
        sections["synopsis"] = hook
        block.append("")
        block.append(f"{cfg.icon('synopsis')} {hook}")

    # --- what to expect ---------------------------------------------------
    if _ov(opts, "expect"):
        bullets = [b for b in (ov.get("bullets") or []) if str(b).strip()]
        if not bullets:
            bullets = make_expect_bullets(title, opts.variant, opts.expect_count)
        if bullets:
            sections["expect"] = "\n".join(bullets)
            block.append("")
            block.append(f"{cfg.icon('expect')} Expect:")
            block.extend(f"{cfg.icon('bullet')} {b}" for b in bullets)

    # --- specs / language / cast / rating ---------------------------------
    fact_lines: List[str] = []
    if _ov(opts, "specs"):
        line = _specs_line(title, cfg)
        if line.strip():
            fact_lines.append(line)
    if _ov(opts, "storage", False):
        fact_lines.append(_storage_line(title, cfg))
    if _ov(opts, "language"):
        langs = title.audio_languages or ([cfg.get("default_language", "English")]
                                          if cfg.get("default_language") else [])
        if langs:
            fact_lines.append(f"{cfg.icon('language')} {', '.join(langs[:3])}")
    if _ov(opts, "cast") and title.cast:
        limit = int(cfg.get("max_cast", 6) or 6)
        fact_lines.append(f"{cfg.icon('cast')} " + " | ".join(title.cast[:limit]))
    elif _ov(opts, "cast"):
        warnings.append("No cast list — add one by hand or connect TMDB to fill it in.")
    if _ov(opts, "rating") and title.rating:
        fact_lines.append(f"{cfg.icon('rating')} {title.rating}")
    elif _ov(opts, "rating"):
        warnings.append("No age rating — add one by hand or connect TMDB.")

    if fact_lines:
        block.append("")
        block.extend(fact_lines)

    # --- why we recommend it ----------------------------------------------
    if _ov(opts, "why"):
        why = why_override or make_why(title, opts.variant)
        sections["why"] = why
        block.append("")
        block.append(f"{cfg.icon('why')} Why {cfg.brand} Recommends It:")
        block.append(why)

    # --- trailer ------------------------------------------------------------
    if _ov(opts, "trailer") and title.trailer_url:
        block.append("")
        block.append(f"{cfg.icon('trailer')} Trailer: {title.trailer_url}")
    elif _ov(opts, "trailer"):
        warnings.append("No trailer link yet — add one, or switch the Trailer section off.")

    # --- tagline --------------------------------------------------------------
    if _ov(opts, "tagline"):
        tagline = tagline_override or make_tagline(title, opts.variant)
        sections["tagline"] = tagline
        block.append("")
        block.append(f"{cfg.icon('tagline')} {tagline}")

    # --- call to action ---------------------------------------------------------
    if _ov(opts, "cta"):
        if keyword_override:
            title.dm_keyword = keyword_override
        keyword = dm_keyword(title)
        template = ov.get("cta") or cfg.get(
            "cta_template", '\U0001F4E9 DM "{keyword}" for {resolutions} ({cta_tail})')
        cta = template.format(
            keyword=keyword,
            resolutions=_resolutions_phrase(title, cfg),
            cta_tail=cfg.get("cta_tail", "flash or phone ready"),
            brand=cfg.brand,
            title=title.name,
        )
        sections["cta"] = cta
        block.append("")
        block.append(cta)

    # --- signature ----------------------------------------------------------
    hash_block = ""
    if cfg.get("include_hashtags") or _ov(opts, "hashtags", False):
        hash_block = "\n" + _hashtags(title, cfg).strip()
    if _ov(opts, "signature"):
        sig = cfg.get("signature", "— {brand} {emoji}").format(
            brand=cfg.brand, emoji=cfg.get("brand_footer_emoji", "\U0001F37F"))
        block.append("")
        block.append(sig + hash_block)
    elif hash_block:
        block.append(hash_block.strip())

    text = "\n".join(block).strip()
    text = _tidy(text)
    return Caption(text=text, title_id=title.id, title_name=title.name,
                   hashtags=hash_block.strip(), warnings=warnings,
                   char_count=len(text), sections=sections)


def _tidy(text: str) -> str:
    lines = [ln.rstrip() for ln in text.split("\n")]
    out = []
    for ln in lines:
        if ln.strip() == "" and (not out or out[-1].strip() == ""):
            continue
        out.append(ln)
    while out and out[-1].strip() == "":
        out.pop()
    return "\n".join(out)


def limit_report(text: str, cfg: Config) -> List[Dict[str, Any]]:
    limits = cfg.get("limits", {}) or {}
    n = len(text)
    report = []
    for name, cap in limits.items():
        try:
            cap = int(cap)
        except (TypeError, ValueError):
            continue
        report.append({"platform": name, "limit": cap, "chars": n, "fits": n <= cap})
    return report

