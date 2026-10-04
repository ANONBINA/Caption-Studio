"""Bounded, single-process background exports with persistent status and artifacts."""
from __future__ import annotations

import json
import logging
import threading
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .export import safe_filename, to_html, to_markdown, write_batch_csv
from .store import _save_json

log = logging.getLogger(__name__)


class JobManager:
    def __init__(self, root):
        self.root = Path(root) / "exports"
        self.root.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="export")
        self.jobs = {}
        self.cancelled = set()
        for path in self.root.glob("*/status.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                if job["status"] in ("queued", "running"):
                    job.update(status="interrupted", error="Application stopped; submit again.")
                    _save_json(str(path), job)
                self.jobs[job["id"]] = job
            except (ValueError, KeyError, OSError):
                log.warning("Ignoring invalid job status: %s", path)

    def _save(self, job):
        _save_json(str(self.root / job["id"] / "status.json"), job)

    def submit(self, titles, render, formats):
        with self.lock:
            if sum(j["status"] in ("queued", "running") for j in self.jobs.values()) >= 4:
                raise ValueError("Four exports are already active. Wait for one to finish.")
            job = {"id": uuid.uuid4().hex, "status": "queued", "total": len(titles),
                   "completed": 0, "created_at": datetime.now(timezone.utc).isoformat(),
                   "formats": formats, "error": None}
            self.jobs[job["id"]] = job
            self._save(job)
            self.pool.submit(self._run, job, titles, render, formats)
            return dict(job)

    def _run(self, job, titles, render, formats):
        ident = job["id"]
        directory = self.root / ident
        try:
            with self.lock:
                job["status"] = "running"
                self._save(job)
            pairs = []
            with ThreadPoolExecutor(max_workers=4) as workers:
                futures = {workers.submit(render, t): t for t in titles}
                for future in as_completed(futures):
                    with self.lock:
                        if ident in self.cancelled:
                            for pending in futures:
                                pending.cancel()
                            job["status"] = "cancelled"
                            self._save(job)
                            return
                    pairs.append((futures[future], future.result()))
                    with self.lock:
                        job["completed"] = len(pairs)
                        self._save(job)
            pairs.sort(key=lambda pair: (pair[0].name.casefold(), pair[0].id))
            with zipfile.ZipFile(directory / "captions.zip.tmp", "w", zipfile.ZIP_DEFLATED) as archive:
                for title, caption in pairs:
                    for fmt in formats:
                        if fmt == "csv":
                            continue
                        if fmt == "txt":
                            content = caption.text
                        elif fmt == "md":
                            content = to_markdown(caption)
                        elif fmt == "html":
                            content = to_html(caption, title)
                        else:
                            content = json.dumps({"title": title.name, "text": caption.text,
                                                  "warnings": caption.warnings},
                                                 ensure_ascii=False, indent=2)
                        archive.writestr(title.id + "_" + safe_filename(title.name, fmt), content)
                if "csv" in formats:
                    path = directory / "captions.csv"
                    write_batch_csv(pairs, str(path))
                    archive.write(path, "captions.csv")
                    path.unlink()
                archive.writestr("manifest.json", json.dumps([
                    {"id": t.id, "title": t.name, "warnings": c.warnings,
                     "characters": c.char_count} for t, c in pairs], ensure_ascii=False, indent=2))
            (directory / "captions.zip.tmp").replace(directory / "captions.zip")
            with self.lock:
                job["status"] = "cancelled" if ident in self.cancelled else "completed"
                self._save(job)
        except Exception:
            log.exception("Export failed: %s", ident)
            with self.lock:
                job.update(status="failed", error="Export failed. Check the server log and retry.")
                self._save(job)
        finally:
            with self.lock:
                self.cancelled.discard(ident)
            (directory / "captions.zip.tmp").unlink(missing_ok=True)

    def get(self, ident):
        with self.lock:
            return dict(self.jobs[ident]) if ident in self.jobs else None

    def list(self):
        with self.lock:
            return sorted((dict(j) for j in self.jobs.values()),
                          key=lambda j: j["created_at"], reverse=True)[:50]

    def cancel(self, ident):
        with self.lock:
            job = self.jobs.get(ident)
            if not job:
                return None
            if job["status"] in ("queued", "running"):
                self.cancelled.add(ident)
            return dict(job)

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=False)
