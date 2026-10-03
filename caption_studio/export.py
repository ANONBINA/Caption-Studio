"""Export captions to files: .txt, .md, .html, .json and .csv."""
from __future__ import annotations

import csv
import html
import json
import os
import re
from typing import Iterable, List, Tuple

from .caption import Caption
from .models import Title


def safe_filename(name: str, ext: str = "txt") -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "_", name or "caption").strip("_").lower()
    base = re.sub(r"_+", "_", base)[:80] or "caption"
    return f"{base}.{ext}"


def to_markdown(caption: Caption) -> str:
    out = []
    for line in caption.text.split("\n"):
        if not line.strip():
            out.append("")
            continue
        if line.startswith(("✅", "•", "-")):
            out.append(f"- {line.lstrip('✅•- ').strip()}")
        else:
            out.append(line)
    return "\n".join(out)


def to_html(caption: Caption, title: Title | None = None, brand: str = "") -> str:
    body = html.escape(caption.text).replace("\n", "<br>")
    meta = ""
    if title is not None:
        meta = (f"<p class='meta'>{html.escape(title.kind_label)} · "
                f"{html.escape(title.year_label)} · {html.escape(title.resolution_label)}"
                f" · {html.escape(title.size_label)}</p>")
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Caption</title><style>"
        "body{background:#0f1115;color:#e8eaed;font:16px/1.6 -apple-system,Segoe UI,Roboto,"
        "Helvetica,Arial,sans-serif;margin:0;padding:32px}"
        ".card{max-width:640px;margin:0 auto;background:#171a21;border:1px solid #262b36;"
        "border-radius:14px;padding:28px}"
        "p.caption{white-space:pre-wrap;margin:0}"
        ".meta{color:#8b93a7;font-size:13px;margin:0 0 16px}"
        "</style></head><body><div class='card'>"
        f"{meta}<p class='caption'>{body}</p></div></body></html>"
    )


def write_caption(caption: Caption, out_dir: str, formats: Iterable[str] = ("txt",),
                  title: Title | None = None, brand: str = "") -> List[str]:
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for fmt in formats:
        fmt = fmt.lower().lstrip(".")
        path = os.path.join(out_dir, safe_filename(caption.title_name, fmt))
        if fmt == "txt":
            content = caption.text
        elif fmt == "md":
            content = to_markdown(caption)
        elif fmt == "html":
            content = to_html(caption, title, brand)
        elif fmt == "json":
            content = json.dumps({"title": caption.title_name, "caption": caption.text,
                                  "warnings": caption.warnings}, indent=2, ensure_ascii=False)
        else:
            continue
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        written.append(path)
    return written


def write_batch_csv(pairs: List[Tuple[Title, Caption]], path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["title", "kind", "year", "genres", "resolutions",
                         "seasons", "episodes", "dm_keyword", "chars",
                         "warnings", "caption"])
        for t, c in pairs:
            from .creative import dm_keyword
            writer.writerow([t.name, t.kind_label, t.year_label, " | ".join(t.genres),
                             " / ".join(t.resolutions), t.seasons, t.episodes,
                             dm_keyword(t), c.char_count,
                             "; ".join(c.warnings), c.text])
    return path


def write_index_html(pairs: List[Tuple[Title, Caption]], path: str, brand: str = "") -> str:
    """One self-contained HTML page containing every generated caption."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    cards = []
    for t, c in pairs:
        cards.append(
            "<section class='card'><h2>{h}</h2><p class='meta'>{meta}</p>"
            "<pre>{body}</pre>{warn}</section>".format(
                h=html.escape(f"{t.name} ({t.year_label})"),
                meta=html.escape(f"{t.kind_label} · {' | '.join(t.genres) or '—'} · "
                                 f"{t.resolution_label or '—'} · {t.size_label}"),
                body=html.escape(c.text),
                warn=("" if not c.warnings else
                      "<p class='warn'>⚠ " + html.escape(" ".join(c.warnings)) + "</p>"),
            ))
    head = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(brand or 'Caption')} — generated captions</title><style>"
        "body{background:#0f1115;color:#e8eaed;font:15px/1.6 -apple-system,Segoe UI,Roboto,"
        "Helvetica,Arial,sans-serif;margin:0;padding:32px}"
        "h1{font-size:22px;margin:0 0 4px}.sub{color:#8b93a7;margin:0 0 28px}"
        ".grid{display:grid;gap:18px;grid-template-columns:repeat(auto-fill,minmax(420px,1fr))}"
        ".card{background:#171a21;border:1px solid #262b36;border-radius:14px;padding:20px}"
        ".card h2{font-size:16px;margin:0 0 4px}"
        ".meta{color:#8b93a7;font-size:12px;margin:0 0 12px}"
        "pre{white-space:pre-wrap;font:inherit;margin:0}"
        ".warn{color:#f0b429;font-size:12px;margin:12px 0 0}"
        "</style></head><body>"
        f"<h1>{html.escape(brand or 'Captions')}</h1>"
        f"<p class='sub'>{len(pairs)} captions · regenerated automatically by Caption Studio</p>"
        "<div class='grid'>"
    )
    page = head + "".join(cards) + "</div></body></html>"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)
    return path
