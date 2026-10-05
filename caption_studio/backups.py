"""Local snapshots. Restore only server-created archives, never arbitrary paths."""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class Backups:
    def __init__(self, store):
        self.store = store
        self.root = Path(store.root)
        self.directory = self.root / "backups"
        self.directory.mkdir(exist_ok=True)

    def list(self):
        return [{"id": p.stem, "bytes": p.stat().st_size}
                for p in sorted(self.directory.glob("*.zip"), reverse=True)]

    def path(self, ident):
        if not re.fullmatch(r"[0-9TZ-]+_[a-f0-9]{8}", ident):
            raise ValueError("Invalid backup ID")
        path = self.directory / (ident + ".zip")
        if not path.is_file():
            raise ValueError("Backup not found")
        return path

    def create(self, reason="manual"):
        with self.store._lock:
            ident = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid4().hex[:8]
            path = self.directory / (ident + ".zip")
            manifest = {"version": 1, "reason": reason, "files": {}}
            files = [self.root / "config.json", *sorted((self.root / "data").glob("*.json")),
                     *sorted((self.root / "data").glob("*.csv"))]
            with zipfile.ZipFile(str(path) + ".tmp", "w", zipfile.ZIP_DEFLATED) as archive:
                for file in files:
                    if not file.is_file() or file.is_symlink():
                        continue
                    name = file.relative_to(self.root).as_posix()
                    content = file.read_bytes()
                    manifest["files"][name] = hashlib.sha256(content).hexdigest()
                    archive.writestr(name, content)
                archive.writestr("manifest.json", json.dumps(manifest))
            Path(str(path) + ".tmp").replace(path)
            # Bound automatic snapshots only; manual snapshots are kept until removed by operator.
            automatic = []
            for old in sorted(self.directory.glob("*.zip"), reverse=True):
                with zipfile.ZipFile(old) as archive:
                    if json.loads(archive.read("manifest.json"))["reason"] != "manual":
                        automatic.append(old)
            for old in automatic[10:]:
                old.unlink()
            return {"id": ident, "bytes": path.stat().st_size}

    def restore(self, ident):
        with self.store._lock:
            payloads = {}
            with zipfile.ZipFile(self.path(ident)) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                if manifest.get("version") != 1:
                    raise ValueError("Unsupported backup version")
                if sum(i.file_size for i in archive.infolist()) > 1024 * 1024 * 1024:
                    raise ValueError("Backup exceeds the 1 GB restore limit")
                for name, checksum in manifest["files"].items():
                    p = Path(name)
                    if not (name == "config.json" or
                            (len(p.parts) == 2 and p.parts[0] == "data" and
                             p.suffix in (".json", ".csv"))):
                        raise ValueError("Unsafe backup member")
                    content = archive.read(name)
                    if hashlib.sha256(content).hexdigest() != checksum:
                        raise ValueError("Backup checksum mismatch")
                    if p.suffix == ".json":
                        value = json.loads(content)
                        if not isinstance(value, dict):
                            raise ValueError("Invalid JSON state")
                    payloads[name] = content
            if "config.json" not in payloads:
                raise ValueError("Backup is missing configuration")
            safety = self.create("before-restore")
            # All archive members have been validated before changing live files.
            for name, content in payloads.items():
                destination = self.root / name
                temporary = destination.with_suffix(destination.suffix + ".restore")
                temporary.write_bytes(content)
                temporary.replace(destination)
            for file in (self.root / "data").iterdir():
                if file.suffix in (".csv", ".json") and file.relative_to(self.root).as_posix() not in payloads:
                    file.unlink()
            from .config import Config
            from .store import _load_json
            self.store.config = Config.load(str(self.root / "config.json"))
            self.store.enriched = _load_json(self.store.enriched_path)
            self.store.overrides = _load_json(self.store.overrides_path)
            self.store.reload()
            return {"ok": True, "safety_backup": safety["id"], "stats": self.store.stats()}
