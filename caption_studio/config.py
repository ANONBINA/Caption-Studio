"""Configuration for Caption Studio.

All user-facing settings live in ``config.json`` next to the project root so you
can edit them by hand or from the web UI.  Everything has a sane default, so the
project works with zero setup.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")

DEFAULT_CONFIG: Dict[str, Any] = {
    # ---- Branding -----------------------------------------------------
    "brand": "Plugent",            # <-- change this to your brand name
    "brand_footer_emoji": "\U0001F37F",   # popcorn
    "signature": "— {brand} {emoji}",

    # ---- Call to action -----------------------------------------------
    "cta_template": "\U0001F4E9 DM \"{keyword}\" for {resolutions} ({cta_tail})",
    "cta_tail": "flash or phone ready",
    "cta_fallback_resolution": "720p / 1080p",

    # ---- Emoji map ------------------------------------------------------
    # The sample caption uses one emoji per line.  Swap any of these to
    # re-skin every caption you generate.
    "icons": {
        "title_movie": "\U0001F3AC",      # clapper board
        "title_series": "\U0001F3AC",     # clapper board (matches the reference post)
        "synopsis": "\U0001F4D6",         # open book
        "expect": "\U0001F50D",           # magnifying glass
        "bullet": "✅",              # check mark
        "specs": "\U0001F4C5",            # calendar
        "language": "\U0001F310",         # globe
        "cast": "⭐",                # star
        "rating": "\U0001F51E",           # eighteen-plus
        "why": "\U0001F4A1",              # light bulb
        "trailer": "\U0001F39E️",     # film frames
        "tagline": "✨",             # sparkles
        "storage": "\U0001F4BE",          # floppy disk
        "cta": "\U0001F4E9",              # envelope with arrow
    },

    # ---- Copy options ---------------------------------------------------
    "default_style": "classic",     # classic | extended
    "default_length": "full",       # full | short | teaser
    "max_genres": 3,
    "max_cast": 6,
    "include_storage_line": False,
    "include_hashtags": False,
    "hashtag_template": "\n#{brand_clean} #{kind} #{genre_clean} #{year}",
    "default_language": "English",

    # ---- Section toggles -------------------------------------------------
    # Any section can be switched off; the caption just skips it.
    "sections": {
        "genres": True,
        "synopsis": True,
        "expect": True,
        "specs": True,
        "language": True,
        "cast": True,
        "rating": True,
        "why": True,
        "trailer": True,
        "tagline": True,
        "cta": True,
        "signature": True,
    },

    # ---- Character limits (used for warnings only) ------------------------
    "limits": {
        "instagram": 2200,
        "whatsapp": 1200,
        "x": 280,
        "facebook": 63206,
    },

    # ---- TMDB (optional) ---------------------------------------------------
    "tmdb_api_key": "",
    "tmdb_language": "en-US",
    "tmdb_auto_trailer": True,

    # ---- Library -----------------------------------------------------------
    "catalog_glob": "data/*.csv",
    "merge_rules": {},   # {"wrong name": "Correct Name"} — filled in by the Merge tool
    "strip_prefixes": ["Watch ", "Wathc "],   # seller prefixes folded away

    # Per-title overrides: {"Breaking Bad": {"dm_keyword": "BREAKING", "tagline": "..."}}
    "overrides": {},
}


def _deep_merge(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    """Thin wrapper around ``config.json`` with attribute access."""

    def __init__(self, data: Optional[Dict[str, Any]] = None, path: str = CONFIG_PATH):
        self.path = path
        self.data: Dict[str, Any] = _deep_merge(DEFAULT_CONFIG, data or {})

    # -- loading / saving -------------------------------------------------
    @classmethod
    def load(cls, path: str = CONFIG_PATH) -> "Config":
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    return cls(json.load(fh), path=path)
            except Exception:
                pass
        cfg = cls(None, path=path)
        cfg.save()
        return cfg

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2, ensure_ascii=False)

    # -- access -----------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.data[key] = value

    @property
    def brand(self) -> str:
        return self.data.get("brand") or "Plugent"

    @property
    def icons(self) -> Dict[str, str]:
        return _deep_merge(DEFAULT_CONFIG["icons"], self.data.get("icons") or {})

    @property
    def sections(self) -> Dict[str, bool]:
        return _deep_merge(DEFAULT_CONFIG["sections"], self.data.get("sections") or {})

    def icon(self, name: str) -> str:
        return self.icons.get(name, "")

    def update(self, patch: Dict[str, Any]) -> None:
        self.data = _deep_merge(self.data, patch)
        self.save()
