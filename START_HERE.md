# Caption Studio 1.1 — implementation handoff

**Delivered:** a tested first incremental release for local desktop / trusted private-LAN use. This is not a claim that the entire ten-sprint roadmap is finished.

The uploaded project has been extracted into `caption-studio/`, upgraded without replacing its Python backend or its vanilla-JavaScript interface, and supplied with your CSV under `data/`. The original uploaded bundle remains unchanged.

## Run it

Python **3.10 or newer** is required. From the extracted project folder:

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux instead: source .venv/bin/activate
python -m pip install -e ".[web,dev]"
caption-studio serve
```

Open **http://127.0.0.1:8000**. The default listener is now loopback-only. Your supplied catalog loads as **599 titles: 330 movies and 269 series** in this environment. Nothing scans, moves, deletes or opens the media files themselves.

If installing the wheel rather than running from this source tree, use an explicit writable workspace:

```bash
python -m pip install "caption_studio-1.1.0-py3-none-any.whl[web]"
caption-studio --root /path/to/workspace serve
```

Place catalogs under that workspace's `data/` directory or import them through the UI. The wheel includes the web UI, but not your private catalog.

### Private LAN only

```bash
caption-studio serve --host 0.0.0.0 --port 8000
```

Connect using this computer's LAN IP. If that hostname/IP is rejected, add it to the comma-separated `CAPTION_STUDIO_ALLOWED_HOSTS` environment variable before starting. Do not use `*`. The application permits local hostnames/addresses and Arena's preview domain; host validation and same-origin write checks help reduce browser-based attacks.

**There is no login or RBAC in this release. Every device that can reach the service can read and change its data.** Restrict access with your firewall to trusted devices. Do not expose it directly to the public internet. The Arena preview is for this development session, not a production security boundary.

## What changed

### Library and interface
- Preserved the existing caption editor, settings, TMDb enrichment, duplicate review and trailer tools.
- Added responsive mobile layout, keyboard-focus styles, accessible library buttons, Escape-to-close and modal focus handling.
- Added 60-title pages with a Load more control, matching-title counts and stale-search cancellation.
- Added release-year range, audio-language and enrichment-status filters. Resolution choices come from the catalog.
- Search now also matches genres, release year and media kind.
- Corrected global sorting: sorting occurs **before** pagination, with stable tie-breaks.
- List responses omit file/folder arrays; full details remain available when selecting a title.

### Caption consistency and provider hook
- Web preview, web save and background export share a caption-building path and saved text overrides.
- Background exports snapshot titles, configuration and overrides so later edits do not change a running batch.
- Added `CaptionProvider` / `TemplateCaptionProvider` in `caption_studio/providers.py`. An adapter can be injected with `create_app(root, caption_provider=...)`.
- No AI provider, credentials, billing, social publishing or external model calls were added. Existing template captions remain the default. TMDb and YouTube checks still make network requests when their tools are used.
- CLI output behavior is retained; the new provider-injection hook is currently for the web application.

### Background exports
- Exports dialog submits jobs and displays persisted status, progress, cancellation and completed ZIP downloads.
- Up to **4 active/queued jobs**, **2 job workers**, and **4 caption-rendering threads per running job**. A job accepts up to 5,000 titles.
- TXT, Markdown, HTML, JSON and CSV are available; each ZIP includes a warning manifest.
- Job artifacts are isolated under `exports/<job-id>/`. Filenames include title IDs to avoid collisions within a job.
- Jobs are visible again after reopening the dialog. On server restart, unfinished jobs become `interrupted`; they do **not** resume automatically.
- Export filters are independent of the library's advanced filters and are labelled accordingly.
- Completed exports are retained until the operator removes them. There is not yet a UI retention policy or bulk-delete operation.
- Legacy synchronous `/api/batch` remains for compatibility. Prefer `/api/jobs` for the new workflow.

### Backups and persistence
- Backups dialog supports creating, downloading and restoring local snapshots.
- Automatic snapshots run once per calendar day **at startup**, and before catalog imports and restores. This is not a continuously running timed scheduler.
- The latest **10 automatic snapshots** are retained. Manual snapshots are retained until removed by the operator.
- Snapshots include `config.json` and CSV/JSON files directly under `data/`. They exclude media, generated exports, caches and catalogs located outside `data/`.
- Restore requires `RESTORE`, validates allowed member paths and SHA-256 checksums, and creates a pre-restore safety snapshot.
- Restore replaces the saved local state and removes CSV/JSON files added to `data/` after the selected snapshot. Checksums detect corruption, not malicious modification by someone with local filesystem access.
- JSON writes use unique temporary files, fsync and atomic replacement. Store mutation methods are serialized inside one process.
- Run **one server process**, not multiple Uvicorn workers. Restore is validated before writing, but is not a filesystem-wide transaction; an OS crash mid-restore can require recovery from the safety snapshot.

### Hardening and packaging
- Bounded pagination, job queue, format choices and caption-option inputs; UTF-8 upload checks and chunked upload-size enforcement.
- Host validation, cross-site write rejection, no-store API responses and MIME-sniffing protection.
- Removed state-changing GET `/api/reload`; use POST instead.
- Spreadsheet formula escaping in CSV exports.
- Default local binding changed from `0.0.0.0` to `127.0.0.1`.
- Web page moved to `caption_studio/web/index.html` and included in wheel package data.
- Corrected Python minimum to 3.10 for the existing union-type annotations.

## Daily workflow

1. Search or filter the library and select a title.
2. Review warnings. Genre-template copy is promotional writing, not verified title-specific knowledge.
3. Fetch TMDb metadata if desired, then verify the match. Existing naming noise and ambiguous matches still need review.
4. Apply manual edits and check the preview before copying/saving.
5. Open **Exports**, choose formats and submit a batch. Warnings travel with the export manifest.
6. Open **Backups** before major edits and download a snapshot to a separate secure disk.

## Security and recovery limits

- Catalogs contain private Windows paths. The source ZIP supplied for you includes your catalog; do not publish it as a public repository.
- Configuration and snapshots may contain a TMDb key. They are **not encrypted**. Prefer the `TMDB_API_KEY` environment variable, restrict filesystem permissions and use OS disk encryption.
- Authentication, roles, TLS termination, secret management, rate limits, audit logging and encryption-at-rest are not implemented here.
- Existing trailer/enrichment network workflows were retained. No live TMDb-key or social-provider acceptance testing was performed.
- Restore accepts existing server-created snapshot IDs, not arbitrary uploaded ZIPs. To recover on a new machine, stop the app, securely copy a trusted snapshot into `backups/`, restart, then restore through the UI.
- For rollback, stop the server, retain a copy of the current workspace, reinstall the previous source from your original bundle, and restore the appropriate configuration/data snapshot. Version 1.1 adds directories rather than migrating catalog schemas.

## Verification

Executed in the development environment:

| Check | Result |
|---|---|
| Original suite before changes | 68 passed |
| Updated pytest suite | **87 passed** |
| Ruff lint, application + tests | Passed |
| JavaScript syntax check | Passed |
| Chromium desktop/mobile smoke flow | Passed; zero uncaught page errors |
| Browser flows | Paginated library, caption selection, background export, ZIP download, backup listing, mobile no horizontal overflow |
| Built wheel | Packaged `caption_studio/web/index.html` verified |
| Supplied catalog quick timing | 599 titles loaded in ~0.33 s; mean in-process filtered search ~1.58 ms over 100 calls |

These timings are observations from this container, not a load-test SLA. There is one upstream Starlette/httpx deprecation warning. Browser tests do not establish full accessibility conformance or cross-browser support.

Re-run:

```bash
python -m pytest
python -m ruff check caption_studio tests
# Optional browser QA, with the server already running on port 8000:
python -m pip install playwright
python -m playwright install --with-deps chromium
python tests/browser/smoke.py
```

The browser smoke script creates a small export against the running workspace; use a disposable workspace for repeated QA. Screenshots are written under `qa/`.

## Remaining full-roadmap implementation

| Area | Current status | Next acceptance gate |
|---|---|---|
| UI/UX | Incremental responsive upgrade delivered | User acceptance and broader accessibility/browser testing |
| Data/search | Correct pagination/sort and additional filters delivered | Larger-catalog profiling; indexed storage only if justified |
| Advanced NLP/ML | Provider boundary only; templates unchanged | Factuality benchmark, provider selection, cost/latency budgets, fallback tests |
| Batch processing | Bounded threaded exports delivered | Durable resume/retry queue and large-load tests if required |
| External services | Existing TMDb retained | Provider-specific integration testing; IMDb/social only after scope approval |
| Accounts/RBAC | Not implemented | Local/LAN role and authentication design before any untrusted users |
| Backup/export | Snapshots and five export formats delivered | Timed/off-machine backups, encrypted storage and restore-drill automation |
| Analytics/feedback | Existing library stats only | Local event schema, retention/privacy policy, feedback UI and reporting |
| Security | Local-use hardening only | Authentication, TLS, security review and deployment threat model |
| Delivery/operations | Tests, wheel, CI definition, runbook supplied | Run CI in your repository, Windows validation, UAT, release sign-off |

Recommended next development slice: **accounts/permissions plus local feedback/analytics**, followed by caption-quality evaluation and optional provider adapters. Keep the current release local-only until the security gate is passed.

The original sprint durations total **23 weeks**, not 26; a 26-week plan can explicitly reserve three weeks for discovery, UAT and release contingency. No completion dates or team capacity have been assumed.
