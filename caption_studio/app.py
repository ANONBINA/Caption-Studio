"""FastAPI web app for Caption Studio."""
from __future__ import annotations

import copy
import csv
import io
import json
import os
import re
import socket
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Annotated, Any, Dict, List, Literal, Optional
from urllib.parse import urlsplit

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .backups import Backups
from .caption import CaptionOptions, limit_report
from .export import safe_filename, write_batch_csv, write_caption, write_index_html
from .jobs import JobManager
from .models import Title
from .providers import CaptionProvider, TemplateCaptionProvider
from .store import Store, title_key
from .tmdb import TMDBClient, TMDBError, youtube_ok

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(os.path.dirname(__file__), "web")

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
    variant: int = Field(0, ge=0, le=10000)
    style: Optional[Literal["classic", "extended"]] = None
    length: Optional[Literal["full", "short", "teaser"]] = None
    expect_count: int = Field(4, ge=1, le=12)
    sections: Dict[str, bool] = Field(default_factory=dict)
    overrides: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("overrides")
    @classmethod
    def validate_overrides(cls, value):
        for key, item in value.items():
            if key == "bullets":
                if not isinstance(item, list) or len(item) > 30 or any(
                    not isinstance(v, str) or len(v) > 2000 for v in item
                ):
                    raise ValueError("bullets must be a list of up to 30 short strings")
            elif not isinstance(item, (str, bool)) or (isinstance(item, str) and len(item) > 20000):
                raise ValueError("Overrides must be text or section switches")
        return value


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
    default_style: Optional[Literal["classic", "extended"]] = None
    default_length: Optional[Literal["full", "short", "teaser"]] = None
    include_hashtags: Optional[bool] = None
    tmdb_api_key: Optional[str] = None
    default_language: Optional[str] = None
    max_cast: Optional[int] = Field(None, ge=0, le=30)
    max_genres: Optional[int] = Field(None, ge=0, le=10)


class ExportRequest(BaseModel):
    ids: List[str] = Field(default_factory=list, max_length=5000)
    q: str = Field("", max_length=300)
    kind: Literal["", "movie", "series"] = ""
    genre: str = ""
    resolution: str = ""
    limit: int = Field(1000, ge=1, le=5000)
    options: CaptionRequest = Field(default_factory=CaptionRequest)
    formats: List[Literal["txt", "md", "html", "json", "csv"]] = Field(
        default_factory=lambda: ["txt", "csv"], min_length=1, max_length=5)


class RestoreRequest(BaseModel):
    confirm: Literal["RESTORE"]


def create_app(root: str = ROOT, caption_provider: Optional[CaptionProvider] = None) -> FastAPI:
    store = Store(root)
    provider = caption_provider or TemplateCaptionProvider()
    backups = Backups(store)
    jobs = JobManager(root)

    @asynccontextmanager
    async def lifespan(app):
        # A daily startup snapshot, plus pre-import snapshots, works without a scheduler.
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        if not any(item["id"].startswith(today) for item in backups.list()):
            backups.create("daily-startup")
        try:
            yield
        finally:
            jobs.close()

    app = FastAPI(title="Caption Studio", version="1.1.0", docs_url="/api/docs",
                  lifespan=lifespan)
    allowed_hosts = ["localhost", "127.0.0.1", "[::1]", "testserver", "*.e2b.app",
                     socket.gethostname()]
    try:
        allowed_hosts.extend(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    allowed_hosts.extend(h.strip() for h in os.environ.get(
        "CAPTION_STUDIO_ALLOWED_HOSTS", "").split(",") if h.strip())
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    app.state.store = store
    app.state.jobs = jobs

    @app.middleware("http")
    async def local_security(request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "Cross-origin writes are not allowed."}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Cross-site writes are not allowed."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "1.1.0", "mode": "trusted-local",
                "titles": len(store.library.titles), "caption_provider": provider.name}

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

    def _build(t: Title, req: CaptionRequest, config=None, overrides=None):
        config = config or store.config
        opts = CaptionOptions.from_dict(req.model_dump(), config)
        stored = (store.overrides if overrides is None else overrides).get(title_key(t.name), {})
        for key in ("why", "cta", "tagline", "synopsis", "bullets"):
            if key in stored and key not in opts.overrides:
                opts.overrides[key] = stored[key]
        return provider.generate(t, config, opts), opts

    def _caption_payload(t: Title, req: CaptionRequest):
        caption, opts = _build(t, req)
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
    def titles(q: str = Query("", max_length=300), kind: str = "", genre: str = "",
               resolution: str = "", limit: int = Query(60, ge=1, le=500),
               offset: int = Query(0, ge=0),
               sort: Literal["name", "year", "size", "newest"] = "name",
               year_min: Optional[int] = Query(None, ge=1800, le=2100),
               year_max: Optional[int] = Query(None, ge=1800, le=2100),
               language: str = "", enriched: Optional[bool] = None):
        if year_min and year_max and year_min > year_max:
            raise HTTPException(422, "Minimum year must not exceed maximum year.")
        results, total = store.library.search(q, kind, genre, resolution, limit, offset,
                                              sort, year_min, year_max, language, enriched)
        # File paths and full episode lists are detail-only: small lazy-loaded list payloads.
        items = []
        for title in results:
            item = title.to_dict()
            for field in ("files", "folders"):
                item.pop(field, None)
            items.append(item)
        return {"total": total, "count": len(items), "items": items,
                "next_offset": offset + len(items) if offset + len(items) < total else None}

    @app.get("/api/facets")
    def facets():
        return {"languages": sorted({v for t in store.library.titles for v in t.audio_languages}),
                "resolutions": sorted({v for t in store.library.titles for v in t.resolutions})}

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
    def caption_get(tid: str, variant: int = Query(0, ge=0, le=10000),
                    style: Literal["", "classic", "extended"] = "",
                    length: Literal["", "full", "short", "teaser"] = "",
                    expect_count: int = Query(4, ge=1, le=12)):
        req = CaptionRequest(variant=variant, style=style or None, length=length or None,
                             expect_count=expect_count)
        return _caption_payload(_title(tid), req)

    @app.post("/api/caption/{tid}/save")
    def save_caption(tid: str, req: CaptionRequest):
        t = _title(tid)
        cap, _ = _build(t, req)
        out_dir = os.path.join(store.root, "out")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, t.id + "_" + safe_filename(t.name, "txt"))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(cap.text)
        return {"path": path}

    @app.post("/api/batch")
    def batch(request: ExportRequest):
        payload = request.model_dump()
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
            cap, _ = _build(t, req)
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
    def batch_download(q: str = "", kind: str = "", limit: int = Query(500, ge=1, le=5000)):
        results, _ = store.library.search(q, kind, "", "", limit, 0)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            manifest = []
            for t in results:
                cap, _ = _build(t, CaptionRequest())
                zf.writestr(t.id + "_" + safe_filename(t.name, "txt"), cap.text)
                manifest.append({"title": t.name, "chars": cap.char_count,
                                 "warnings": cap.warnings})
            zf.writestr("_manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        buf.seek(0)
        return Response(buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="captions.zip"'})

    # -- persistent background exports ----------------------------------------
    @app.post("/api/jobs", status_code=202)
    def create_job(req: ExportRequest):
        with store._lock:
            if req.ids:
                chosen = list(dict.fromkeys(req.ids))
                titles = [_title(ident) for ident in chosen]
            else:
                titles, _ = store.library.search(req.q, req.kind, req.genre, req.resolution,
                                                req.limit, 0)
            if not titles:
                raise HTTPException(400, "No matching titles.")
            titles = copy.deepcopy(titles)
            config, overrides = copy.deepcopy(store.config), copy.deepcopy(store.overrides)
        try:
            return jobs.submit(titles, lambda t: _build(t, req.options, config, overrides)[0],
                               list(dict.fromkeys(req.formats)))
        except ValueError as exc:
            raise HTTPException(429, str(exc)) from exc

    @app.get("/api/jobs")
    def list_jobs():
        return jobs.list()

    @app.get("/api/jobs/{ident}")
    def get_job(ident: str):
        job = jobs.get(ident)
        if not job:
            raise HTTPException(404, "Job not found")
        return job

    @app.post("/api/jobs/{ident}/cancel")
    def cancel_job(ident: str):
        get_job(ident)
        return jobs.cancel(ident)

    @app.get("/api/jobs/{ident}/download")
    def download_job(ident: str):
        if get_job(ident)["status"] != "completed":
            raise HTTPException(409, "Export is not complete")
        return FileResponse(jobs.root / ident / "captions.zip", media_type="application/zip",
                            filename="captions-" + ident[:8] + ".zip")

    # -- backup management -----------------------------------------------------
    @app.get("/api/backups")
    def list_backups():
        return backups.list()

    @app.post("/api/backups", status_code=201)
    def create_backup():
        return backups.create()

    @app.get("/api/backups/{ident}/download")
    def download_backup(ident: str):
        try:
            return FileResponse(backups.path(ident), filename="caption-studio-" + ident + ".zip")
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/backups/{ident}/restore")
    def restore_backup(ident: str, req: RestoreRequest):
        try:
            return backups.restore(ident)
        except (ValueError, KeyError, zipfile.BadZipFile) as exc:
            raise HTTPException(400, "Invalid backup; restore was not completed.") from exc

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
        with store._lock:
            store.config.update(patch)
        return get_settings()

    # -- trailers --------------------------------------------------------------
    @app.post("/api/trailers/check")
    def trailers_check():
        """Verify every stored trailer link against YouTube (cached per video)."""
        urls = [(t, t.trailer_url) for t in store.library.titles if t.trailer_url]
        with ThreadPoolExecutor(max_workers=16) as pool:
            verdicts = list(pool.map(youtube_ok, [u for _, u in urls]))
        dead = [{"id": t.id, "name": t.name, "url": u}
                for (t, u), ok in zip(urls, verdicts) if not ok]
        return {"checked": len(urls), "ok": len(urls) - len(dead), "dead": dead}

    @app.post("/api/trailers/fix")
    def trailers_fix():
        """Replace dead trailers with fresh TMDB picks, or remove them.

        Without a TMDB key a dead link is simply cleared, which brings back
        the caption's "No trailer link yet" warning instead of a dead URL.
        """
        report = trailers_check()
        cfg = store.config
        key = cfg.get("tmdb_api_key") or os.environ.get("TMDB_API_KEY", "")
        client = TMDBClient(key, cfg.get("tmdb_language", "en-US")) if key else None
        replaced, removed = [], []
        for item in report["dead"]:
            title = store.get(item["id"])
            if title is None:
                continue
            replacement = None
            if client is not None:
                try:
                    replacement = client.trailer_for(title, refresh=True)
                except TMDBError:
                    replacement = None
            store.repair_trailer(title.name, replacement)
            entry = {"id": title.id, "name": title.name, "url": replacement}
            (replaced if replacement else removed).append(entry)
        return {"checked": report["checked"], "dead_found": len(report["dead"]),
                "replaced": replaced, "removed": removed}

    # -- catalogs ---------------------------------------------------------------
    @app.post("/api/catalogs")
    async def upload_catalog(file: Annotated[UploadFile, File()]):
        """Import a scanner CSV: save it into data/ and reload the library."""
        name = _safe_catalog_name(file.filename or "")
        content = bytearray()
        while chunk := await file.read(1024 * 1024):
            content.extend(chunk)
            if len(content) > MAX_CATALOG_UPLOAD_BYTES:
                raise HTTPException(413, "File too large (200 MB limit).")
        if not content:
            raise HTTPException(400, "The uploaded file is empty.")
        if len(content) > MAX_CATALOG_UPLOAD_BYTES:
            raise HTTPException(413, "File too large (200 MB limit).")
        try:
            # Reject malformed encoding before replacing an existing catalog.
            next(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
        except (UnicodeError, csv.Error, StopIteration) as exc:
            raise HTTPException(400, "Use a UTF-8 CSV with a header row.") from exc
        backups.create("before-import")
        dest = os.path.join(store.root, "data", name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        import tempfile
        with store._lock:
            fd, temporary = tempfile.mkstemp(dir=os.path.dirname(dest), suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(content)
                os.replace(temporary, dest)
                store.reload()
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        # The loader skips CSVs that don't match the scanner format — surface
        # that to the caller instead of failing silently.
        return {
            "ok": True,
            "file": name,
            "loaded": name in store.library.sources,
            "stats": store.stats(),
            "sources": store.library.sources,
        }

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
    uvicorn.run(create_app(), host="127.0.0.1", port=8000, log_level="info")

