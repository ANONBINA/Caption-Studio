"""FastAPI web app for Caption Studio."""
from __future__ import annotations

import io
import json
import os
import re
import zipfile
from typing import Annotated, Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from .caption import CaptionOptions, build_caption, limit_report
from .export import safe_filename, write_batch_csv, write_caption, write_index_html
from .models import Title
from .store import Store, title_key
from .tmdb import TMDBClient, TMDBError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "web")

# Scanner CSVs are a few MB even for thousands of rows; this is just a guard
# against someone piping a video file into the endpoint.
MAX_CATALOG_UPLOAD_BYTES = 200 * 1024 * 1024


def _safe_catalog_name(name: str) -> str:
    """Reduce an uploaded filename to a safe basename inside data/."""
    base = os.path.basename(name or "").strip()
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base).strip(". ")
    if not base:
        raise HTTPException(400, "No filename provided.")
    if not base.lower().endswith(".csv"):
        raise HTTPException(400, "Only .csv files can be imported.")
    return base


class CaptionRequest(BaseModel):
    variant: int = 0
    style: Optional[str] = None
    length: Optional[str] = None
    expect_count: int = 4
    sections: Dict[str, bool] = Field(default_factory=dict)
    overrides: Dict[str, Any] = Field(default_factory=dict)


class OverrideRequest(BaseModel):
    dm_keyword: Optional[str] = None
    synopsis: Optional[str] = None
    tagline: Optional[str] = None
    genres: Optional[str] = None      # "Comedy | Sitcom | Family"
    cast: Optional[str] = None        # "Jane Kaczmarek | Bryan Cranston"
    rating: Optional[str] = None      # "TV-PG"
    trailer: Optional[str] = None     # youtube url
    why: Optional[str] = None
    bullets: Optional[List[str]] = None


class SettingsRequest(BaseModel):
    brand: Optional[str] = None
    cta_tail: Optional[str] = None
    icons: Optional[Dict[str, str]] = None
    sections: Optional[Dict[str, bool]] = None
    default_style: Optional[str] = None
    default_length: Optional[str] = None
    include_hashtags: Optional[bool] = None
    tmdb_api_key: Optional[str] = None
    default_language: Optional[str] = None
    max_cast: Optional[int] = None
    max_genres: Optional[int] = None


def create_app(root: str = ROOT) -> FastAPI:
    app = FastAPI(title="Caption Studio", docs_url="/api/docs")
    store = Store(root)

    def _title(tid: str) -> Title:
        t = store.get(tid)
        if t is None:
            raise HTTPException(404, f"Unknown title {tid}")
        return t

    def _title_payload(t: Title) -> dict:
        from .store import title_key
        data = t.to_dict()
        data["overrides"] = store.overrides.get(title_key(t.name), {})
        return data

    def _caption_payload(t: Title, req: CaptionRequest):
        opts = CaptionOptions.from_dict(req.model_dump(), store.config)
        # Hand-edited copy lives in data/overrides.json; feed it in unless the
        # caller supplied its own value for this run.
        stored = store.overrides.get(title_key(t.name), {})
        for key in ("why", "cta", "tagline", "synopsis"):
            if stored.get(key) and not opts.overrides.get(key):
                opts.overrides[key] = stored[key]
        if stored.get("bullets") and not opts.overrides.get("bullets"):
            opts.overrides["bullets"] = stored["bullets"]
        caption = build_caption(t, store.config, opts)
        return {
            "text": caption.text,
            "hashtags": caption.hashtags,
            "warnings": caption.warnings,
            "char_count": caption.char_count,
            "limits": limit_report(caption.text, store.config),
            "title": _title_payload(t),
            "options": {
                "variant": opts.variant, "style": opts.style, "length": opts.length,
                "expect_count": opts.expect_count, "sections": opts.sections,
                "overrides": opts.overrides,
            },
            "title_overrides": store.overrides.get(title_key(t.name), {}),
        }

    # -- pages ----------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def index():
        with open(os.path.join(WEB_DIR, "index.html"), "r", encoding="utf-8") as fh:
            return fh.read()

    # -- library ---------------------------------------------------------
    @app.get("/api/stats")
    def stats():
        return store.stats()

    @app.get("/api/titles")
    def titles(q: str = "", kind: str = "", genre: str = "", resolution: str = "",
               limit: int = Query(60, le=500), offset: int = 0, sort: str = "name"):
        results, total = store.library.search(q, kind, genre, resolution, limit, offset)
        if sort == "year":
            results = sorted(results, key=lambda t: -(t.year or 0))
        elif sort == "size":
            results = sorted(results, key=lambda t: -t.total_bytes)
        elif sort == "newest":
            results = sorted(results, key=lambda t: -(t.year or 0))
        return {"total": total, "count": len(results),
                "items": [t.to_dict() for t in results]}

    @app.get("/api/titles/{tid}")
    def get_title(tid: str):
        return _title_payload(_title(tid))

    @app.get("/api/genres")
    def genres():
        return [{"name": g, "count": c} for g, c in store.library.all_genres()]

    # -- captions ---------------------------------------------------------
    @app.post("/api/caption/{tid}")
    def caption(tid: str, req: CaptionRequest):
        return _caption_payload(_title(tid), req)

    @app.get("/api/caption/{tid}")
    def caption_get(tid: str, variant: int = 0, style: str = "", length: str = "",
                    expect_count: int = 4):
        req = CaptionRequest(variant=variant, style=style or None, length=length or None,
                             expect_count=expect_count)
        return _caption_payload(_title(tid), req)

    @app.post("/api/caption/{tid}/save")
    def save_caption(tid: str, req: CaptionRequest):
        t = _title(tid)
        cap = build_caption(t, store.config, CaptionOptions.from_dict(req.model_dump(),
                                                                     store.config))
        out_dir = os.path.join(store.root, "out")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, safe_filename(t.name, "txt"))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(cap.text)
        return {"path": path}

    @app.post("/api/batch")
    def batch(payload: dict):
        ids = payload.get("ids") or []
        if not ids:
            q = payload.get("q", "")
            kind = payload.get("kind", "")
            limit = int(payload.get("limit", 500))
            results, _ = store.library.search(q, kind, "", "", limit, 0)
            titles = results
        else:
            titles = [t for t in store.library.titles if t.id in set(ids)]
        req = CaptionRequest(**(payload.get("options") or {}))
        pairs = []
        for t in titles:
            cap = build_caption(t, store.config,
                                CaptionOptions.from_dict(req.model_dump(), store.config))
            pairs.append((t, cap))
            write_caption(cap, os.path.join(store.root, "out"), ["txt"], t, store.config.brand)
        out_dir = os.path.join(store.root, "out")
        os.makedirs(out_dir, exist_ok=True)
        csv_path = write_batch_csv(pairs, os.path.join(out_dir, "captions.csv"))
        write_index_html(pairs, os.path.join(out_dir, "index.html"), store.config.brand)
        return {
            "count": len(pairs),
            "csv": csv_path,
            "out_dir": out_dir,
            "items": [{"id": t.id, "name": t.name, "chars": c.char_count,
                       "warnings": c.warnings, "text": c.text} for t, c in pairs],
        }

    @app.get("/api/batch/download")
    def batch_download(q: str = "", kind: str = "", limit: int = 500):
        results, _ = store.library.search(q, kind, "", "", limit, 0)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            manifest = []
            for t in results:
                cap = build_caption(t, store.config, CaptionOptions.from_dict({}, store.config))
                zf.writestr(safe_filename(t.name, "txt"), cap.text)
                manifest.append({"title": t.name, "chars": cap.char_count,
                                 "warnings": cap.warnings})
            zf.writestr("_manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        buf.seek(0)
        return Response(buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="captions.zip"'})

    # -- overrides ---------------------------------------------------------
    @app.post("/api/titles/{tid}/override")
    def set_override(tid: str, req: OverrideRequest):
        t = _title(tid)
        store.save_override(t.name, req.model_dump(exclude_none=True))
        return {"ok": True, "title": store.find_by_name(t.name).to_dict()}

    @app.delete("/api/titles/{tid}/override")
    def clear_override(tid: str, fields: str = ""):
        t = _title(tid)
        store.clear_override(t.name, [f for f in fields.split(",") if f] or None)
        return {"ok": True}

    # -- enrichment ---------------------------------------------------------
    @app.post("/api/titles/{tid}/enrich")
    def enrich(tid: str, payload: dict | None = None):
        t = _title(tid)
        cfg = store.config
        key = (payload or {}).get("tmdb_key") or cfg.get("tmdb_api_key") or \
            os.environ.get("TMDB_API_KEY", "")
        if not key:
            raise HTTPException(400, "No TMDB API key set. Add one in Settings → TMDB.")
        try:
            client = TMDBClient(key, cfg.get("tmdb_language", "en-US"))
            result = client.enrich(t, with_trailer=cfg.get("tmdb_auto_trailer", True),
                                   match=(payload or {}).get("tmdb_id"))
        except TMDBError as exc:
            raise HTTPException(502, str(exc)) from exc
        store.save_enriched(t)
        return {"ok": True, "result": result, "title": t.to_dict()}

    @app.post("/api/titles/{tid}/search-tmdb")
    def search_tmdb(tid: str, payload: dict | None = None):
        t = _title(tid)
        cfg = store.config
        key = (payload or {}).get("tmdb_key") or cfg.get("tmdb_api_key") or \
            os.environ.get("TMDB_API_KEY", "")
        if not key:
            raise HTTPException(400, "No TMDB API key set.")
        try:
            client = TMDBClient(key, cfg.get("tmdb_language", "en-US"))
            kind = "tv" if t.is_series else "movie"
            results = client.search(kind, t.name, t.year)
        except TMDBError as exc:
            raise HTTPException(502, str(exc)) from exc
        return [{"id": r.get("id"), "name": r.get("name") or r.get("title"),
                 "year": (r.get("first_air_date") or r.get("release_date") or "")[:4],
                 "overview": (r.get("overview") or "")[:180]} for r in results[:8]]

    @app.post("/api/titles/{tid}/forget")
    def forget(tid: str):
        t = _title(tid)
        store.forget_enrichment(t.name)
        return {"ok": True}

    # -- duplicates ----------------------------------------------------------
    @app.get("/api/duplicates")
    def duplicates(cutoff: float = 0.9):
        return store.duplicates(cutoff=cutoff)

    @app.post("/api/merge")
    def merge(payload: dict):
        keep, other = payload.get("keep"), payload.get("merge")
        if not keep or not other:
            raise HTTPException(400, "keep and merge are required")
        try:
            store.merge(keep, other)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"ok": True, "stats": store.stats()}

    # -- settings --------------------------------------------------------------
    @app.get("/api/settings")
    def get_settings():
        cfg = store.config
        return {
            "brand": cfg.brand,
            "cta_tail": cfg.get("cta_tail"),
            "icons": cfg.icons,
            "sections": cfg.sections,
            "default_style": cfg.get("default_style"),
            "default_length": cfg.get("default_length"),
            "include_hashtags": cfg.get("include_hashtags"),
            "default_language": cfg.get("default_language"),
            "max_cast": cfg.get("max_cast"),
            "max_genres": cfg.get("max_genres"),
            "tmdb_configured": bool(cfg.get("tmdb_api_key")),
            "hashtag_template": cfg.get("hashtag_template"),
            "cta_template": cfg.get("cta_template"),
            "limits": cfg.get("limits"),
        }

    @app.post("/api/settings")
    def post_settings(req: SettingsRequest):
        patch = {k: v for k, v in req.model_dump().items() if v is not None}
        if "icons" in patch:
            patch["icons"] = {**store.config.icons, **patch["icons"]}
        if "sections" in patch:
            patch["sections"] = {**store.config.sections, **patch["sections"]}
        store.config.update(patch)
        return get_settings()

    # -- catalogs ---------------------------------------------------------------
    @app.post("/api/catalogs")
    async def upload_catalog(file: Annotated[UploadFile, File()]):
        """Import a scanner CSV: save it into data/ and reload the library."""
        name = _safe_catalog_name(file.filename or "")
        content = await file.read()
        if not content:
            raise HTTPException(400, "The uploaded file is empty.")
        if len(content) > MAX_CATALOG_UPLOAD_BYTES:
            raise HTTPException(413, "File too large (200 MB limit).")
        dest = os.path.join(store.root, "data", name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(content)
        store.reload()
        # The loader skips CSVs that don't match the scanner format — surface
        # that to the caller instead of failing silently.
        return {
            "ok": True,
            "file": name,
            "loaded": name in store.library.sources,
            "stats": store.stats(),
            "sources": store.library.sources,
        }

    @app.get("/api/reload")
    def reload_catalogs():
        store.reload()
        return {"ok": True, "stats": store.stats(),
                "sources": store.library.sources}

    @app.post("/api/reload")
    def reload():
        store.reload()
        return {"ok": True, "stats": store.stats(),
                "sources": store.library.sources}

    return app


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(), host="0.0.0.0", port=8000, log_level="info")
