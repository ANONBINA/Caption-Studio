# Caption Studio

## Version 1.1 — local-workspace upgrade

See [START_HERE.md](START_HERE.md) for setup, verification, recovery, security limits,
and the implementation status of the broader roadmap.


Turns your media-catalog CSVs into scroll-stopping promo captions in the exact
house style of your reference post — same emojis, same section order, same
call-to-action.

```
🎬 Malcolm In The Middle (2000)
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
This is the sitcom that redefined family comedy with its chaotic energy…

🎞️ Trailer: https://youtu.be/xxxx

✨ Dysfunctional, hilarious, and timeless.

📩 DM "MALCOLM" for 720p / 1080p (flash or phone ready)

— Plugent 🍿
```

---

## Quick start

**One-command setup** (creates the venv, installs everything, copies config —
safe to re-run; it only does the steps that are still missing):

```bash
bash scripts/setup.sh        # macOS / Linux / Git Bash on Windows
scripts\setup.bat            # Windows CMD
```

Optional flags, combinable:

```bash
--dev      # also install pytest + ruff (test/lint tooling)
--qrcode   # also install qrcode — scannable QR when you run mobile mode
```

Then run it:

```bash
bash scripts/serve.sh        # web app — http://localhost:8000 (desktop, loopback only)
scripts\serve.bat            # Windows CMD
bash scripts/serve.sh --lan  # mobile mode — prints a QR + URL for your phone
scripts\serve.bat --lan      # Windows CMD, mobile mode
bash scripts/test.sh         # pytest + ruff

# ...or straight from the command line (any shell, after setup)
caption-studio serve
caption-studio caption "Malcolm In The Middle"

# Manual route, if you'd rather do it yourself:
#   python -m venv .venv && .venv/Scripts/activate (Windows) or source .venv/bin/activate
#   pip install -e ".[web]"
# (CLI-only install, no web app: pip install -e .)
# (still works too: python -m caption_studio.cli ...)
```

The web app is the fastest route: search your library, click a title, get a
caption, copy it. No setup, no API key required.

---

## Desktop and mobile

The web UI is responsive — it works on desktop and phone browsers alike. The
`--lan` flag on the serve scripts is what makes a phone able to **reach** the
app at all:

| | |
|---|---|
| **Desktop mode** (default) | binds to `127.0.0.1` only — nothing outside this PC can connect |
| **Mobile mode** (`--lan`)  | binds to all interfaces and prepares everything a phone needs |

Running `serve.sh --lan` (or `serve.bat --lan`) automatically:

1. **Detects this PC's LAN IP** (e.g. `192.168.1.188`) — no need to run `ipconfig`.
2. **Whitelists that IP** via `CAPTION_STUDIO_ALLOWED_HOSTS`, so the app's host
   validation accepts requests from the phone.
3. **Prints the URL** (`http://192.168.1.188:8000`) and, if `--qrcode` was
   installed during setup, a **scannable QR code** — point your phone camera at
   it and tap the link.
4. **Reminds you about the Windows Firewall prompt** — click **Allow** so the
   phone can connect.

Requirements for the phone: same Wi-Fi network as the PC (guest networks and
hotspots usually block device-to-device traffic), and a modern browser — the UI
is the same responsive web app, with the mobile layout from v1.1.

> **Security reminder:** there is no login. In mobile mode every device on the
> network can read and change the library. Use it on a trusted Wi-Fi only, and
> never port-forward it to the internet.

### Troubleshooting mobile mode

| Symptom | Fix |
|---|---|
| "Could not auto-detect your LAN IP" | Find the IPv4 with `ipconfig` and export it: `export CAPTION_STUDIO_ALLOWED_HOSTS=192.168.1.50` (bash) or `set CAPTION_STUDIO_ALLOWED_HOSTS=192.168.1.50` (CMD), then serve with an explicit host: `scripts\serve.bat 192.168.1.50` |
| Phone gets a connection error / times out | Click **Allow** on the Windows Firewall prompt, or allow port 8000 in firewall settings; check both devices are on the same network |
| QR shows but the URL does not load | The QR is cosmetic — type the printed URL manually; check the server is still running |
| "Invalid host header" in the response | Your PC's IP changed (new Wi-Fi) — re-run `--lan`, which re-detects and re-whitelists |
| LAN IP changes often | Set `CAPTION_STUDIO_ALLOWED_HOSTS` permanently in your environment, or reserve the PC's IP in your router's DHCP settings |

---

## Scripts reference

Everything in `scripts/` is idempotent — safe to re-run at any time; each
script only performs the steps that are still missing. `.sh` variants run on
macOS/Linux/Git Bash; `.bat` variants run on Windows CMD.

| Script | Purpose |
|---|---|
| `setup.sh` / `setup.bat` | Full setup: check Python 3.10+ (prefers the real `py` launcher over Windows' Store stub), create `.venv`, install `.[web]`, copy `config.example.json` → `config.json` (never overwrites an existing one), check for a catalog in `data/`, verify the install. Flags: `--dev` (pytest/ruff), `--qrcode` (QR support) |
| `serve.sh` / `serve.bat` | Launch the web app. Auto-runs setup if `.venv` is missing. Desktop mode binds to `127.0.0.1:8000`; `--lan` (or an explicit host) enables mobile mode with QR + firewall hints |
| `test.sh` / `test.bat` | Run pytest + ruff inside the project venv (auto-installs dev deps if missing). `test.sh quick` = pytest only |
| `lan_ip.py` | Helper: prints this PC's LAN IPv4 (used by the serve scripts) |
| `print_qr.py` | Helper: prints an ASCII QR for a URL; failure is cosmetic and never stops the server |

Custom port: pass it as the second argument — `bash scripts/serve.sh --lan 9000`
gives you the phone URL on port 9000.

---

## What it does with your catalog

Your scanner writes **one row per video file**. Caption Studio folds that into
**one card per sellable title**, and repairs the messy bits on the way:

| Problem in the raw CSV | What the loader does |
|---|---|
| 7,758 episode rows | folds into 266 series with real season/episode counts |
| Episodes filed as movies (`"Episode 07"`) | re-files them into the series in that folder |
| `"Watch 24"` and `"24"` listed twice | folds prefixes together (configurable) |
| `"Beauty In Black S01"` + `S02` | one series, both seasons |
| Duplicate copies on D: and E: | counted once, so you never promise 200 episodes for 100 |
| `Grey&039;s Anatomy` | HTML entities unescaped |
| `Apex AAC5 1`, `Code 8 [1080p] [WEBRip]` | release tags stripped |
| Genre only in folder names (`... (2013 Action-Comedy)`) | parsed out, typos fixed (`Theriller` → `Thriller`) |

It also flags likely duplicates (`Duplicates` button) — `13 Reason Why` /
`13 Reasons Why`, `SpongeBob SquarePant` / `SquarePants`,
`House Of Cads` / `House Of Cards` — and merges them with one click.

---

## The three ways to fill in the words

The catalog knows the *files* (year, genre, seasons, episodes, runtime,
resolution, size, languages) but nothing about the *story*. You have three
options, and you can mix them per title:

**1. Auto (default, offline).** Genre playbooks write the hook, the ✅ bullets,
the "why we recommend it" paragraph and the tagline. Deterministic — the same
title always gives the same caption; hit **New wording** to roll another
variant. Good copy, but generic: the UI flags it with a
*"Needs a human touch"* box so you never post a template by accident.

**2. Type it in.** Every part of the caption is editable in the right-hand
panel. Edits are saved per title in `data/overrides.json` and survive a re-scan.

**3. TMDB (best).** Add a free API key and one click fills in the real
synopsis, top-billed cast, age rating, genres, season/episode counts and the
YouTube trailer.

   → themoviedb.org → Settings → API → paste the key into **Settings → TMDB**
   (or into `config.json`, or set the `TMDB_API_KEY` environment variable).
   Results are cached in `.tmdb_cache/`, so it works offline afterwards.
   Trailer picks are **verified against YouTube before they're stored** — a
   deleted video is never saved; the next candidate is tried instead.

---

## Web app

| | |
|---|---|
| Left panel | search by title, filter by type / genre / quality, sort |
| Main | the finished caption, char count, per-platform limit warnings |
| **Copy caption** | to clipboard |
| **New wording** | rolls the next variant of the auto-written copy |
| **Save .txt** / **Download** | writes to `out/` |
| **Fetch from TMDB** | fills real metadata (needs a key) |
| Edit panel | synopsis, bullets, tagline, why, cast, genres, rating, trailer, DM keyword |
| Section toggles | switch any block of the layout on or off |
| **Batch** | generate every matching caption → `out/`, plus a `.zip` and a browsable `index.html` |
| **Import CSV** | upload a new scanner catalog — saved into `data/`, library reloads instantly |
| **Reload** | re-read every catalog in `data/` without restarting |
| **Trailers** | verify every stored trailer link against YouTube; fix dead ones in one click |
| **Duplicates** | find and merge the same title filed under two names |
| **Settings** | brand, CTA wording, every emoji, defaults, TMDB key |

## CLI

```bash
python -m caption_studio.cli stats                       # library summary
python -m caption_studio.cli search "breaking"           # find a title
python -m caption_studio.cli show "Breaking Bad"         # dump everything known

python -m caption_studio.cli caption "2 Guns"            # one caption
python -m caption_studio.cli caption "2 Guns" --variant 3 --style extended
python -m caption_studio.cli caption "2 Guns" --out out/ --format txt md html

python -m caption_studio.cli batch --all --out out/      # all 580 titles
python -m caption_studio.cli batch --query "" --kind movie --limit 100 --out out/

python -m caption_studio.cli enrich "Breaking Bad" --tmdb-key KEY
python -m caption_studio.cli enrich --all --limit 100 --tmdb-key KEY

python -m caption_studio.cli dupes                       # likely duplicates
python -m caption_studio.cli merge t00123 t00456         # merge two ids
python -m caption_studio.cli serve                       # web app
```

`batch` writes one `.txt` per title plus `out/captions.csv` (with a *warnings*
column so you can triage what still needs a human) and `out/index.html` (a
browsable gallery of every caption).

---

## Configuration — `config.json`

Everything you might want to change lives here (or in **Settings** in the UI):

```jsonc
{
  "brand": "Plugent",                 // ← your brand name
  "cta_template": "📩 DM \"{keyword}\" for {resolutions} ({cta_tail})",
  "cta_tail": "flash or phone ready",
  "icons": { "title_movie": "🎬", "expect": "🔍", "bullet": "✅", ... },
  "default_style": "classic",         // classic | extended (adds a size/quality line)
  "default_length": "full",           // full | short | teaser
  "max_genres": 3,
  "max_cast": 6,
  "include_hashtags": false,
  "tmdb_api_key": "",
  "strip_prefixes": ["Watch ", "Wathc "],
  "merge_rules": {},                  // filled in by the Merge tool
  "overrides": {}                     // per-title edits live in data/overrides.json
}
```

**To change the brand:** edit `"brand"` in `config.json` (or Settings → Brand
name). It flows into the "Why *Brand* Recommends It" heading and the sign-off.

**To re-skin the emoji:** every icon in the layout has a named entry under
`"icons"`.

> **Heads-up:** `config.json` is machine-local (it holds your TMDB key and
> merge rules) and is kept out of version control. Fresh clones start from
> `config.example.json` — copy it to `config.json` to begin. The TMDB key can
> also come from the `TMDB_API_KEY` environment variable, which is checked by
> the CLI and the web app. Never commit a real key anywhere.

---

## Adding a newer catalog

**In the web app:** click **Import CSV** in the top bar and pick the file.
It is saved into `data/` and the library reloads automatically — search, filters
and stats update immediately. The **Reload** button re-reads every catalog in
`data/` without a restart.

From disk instead: drop the new `catalog-*.csv` into `data/`, then hit
**Reload** (or restart).

Files are matched on their full path and the most recently scanned record wins,
so old and new catalogs merge instead of double-counting. Your TMDB enrichment
and hand-written edits are keyed by title name and carry over.

> **If a catalog is silently ignored:** the loader only accepts scanner-format
> CSVs — it needs the `full_path`, `media_type`, `resolution_label` and
> `directory_path` columns and at least 50 data rows. Anything else is skipped,
> and **Import CSV warns you when that happens** so a hand-made file never
> disappears without a trace.

### Dead trailer links

TMDB's video list goes stale — videos get deleted or made private. Two
safeguards keep dead YouTube links out of your captions:

1. **At pick time:** every trailer fetched from TMDB is checked against
   YouTube's oEmbed (free, no API key, cached in `.tmdb_cache/`). If the best
   candidate is gone, the next one is tried; if none work, no link is stored.
2. **For links you already have:** click **Trailers** in the top bar. It
   verifies every stored link in parallel and lists the dead ones — **Fix**
   replaces them with a fresh official trailer when a TMDB key is set,
   otherwise removes them so the caption shows a *"No trailer link yet"*
   warning instead of posting a dead URL.

---

## Development

```bash
bash scripts/setup.sh --dev       # one-time: app + dev tools (pytest, ruff)

bash scripts/test.sh              # pytest + ruff — same as CI
bash scripts/test.sh quick        # pytest only, faster loop (scripts\test.bat quick on CMD)
bash scripts/serve.sh             # try your changes in the web app
```

Equivalent manual commands:

```bash
pip install -e ".[web,dev]"       # app + dev tools (pytest, ruff)

pytest                            # run the test suite
caption-studio serve              # try your changes in the web app
ruff check caption_studio tests   # lint (config in pyproject.toml)
```

The tests cover the config layer, catalog name repair and folding, caption
assembly/warnings, and `Store` persistence (overrides, enrichment, merges) —
all against throwaway project roots, never your real `data/`.

---

## Project layout

```
caption_studio/
  config.py      settings + defaults (config.json)
  models.py      the Title dataclass
  catalog.py     CSV → titles: folding, genre/year parsing, name repair
  creative.py    genre playbooks — the offline copy engine
  caption.py     assembles the finished caption
  tmdb.py        optional TMDB enrichment + cache
  store.py       persistence: config, enrichment, overrides, merging
  export.py      .txt / .md / .html / .csv / .zip output
  cli.py         command-line interface
  app.py         FastAPI web app
  web/index.html packaged single-file UI (no CDNs, works offline)
tests/           pytest suite: config, catalog folding, captions, store
scripts/         setup / serve / test helpers (bash + Windows .bat, + lan_ip.py and print_qr.py helpers)
config.example.json   template config for fresh clones
data/            catalogs + enriched.json + overrides.json (git-ignored)
out/            generated captions (git-ignored)
.tmdb_cache/     cached TMDB responses (git-ignored)
```

## Requirements

Python 3.10+. `pip install -e ".[web]"` pulls in `fastapi`, `uvicorn` and
`python-multipart` for the web app (`requirements.txt` still works for a
plain `pip install -r`). The CLI's `caption`, `batch`, `search` and `stats`
commands run on the standard library alone — install FastAPI only if you want
the web app.

Optional extras: `qrcode` (installed by `setup.sh --qrcode` / `setup.bat
--qrcode`) enables the scannable QR code in mobile mode; `pytest` + `ruff`
(`--dev`) are only needed for development. On Windows, real Python from
python.org is recommended — the Microsoft Store `python` alias is a stub the
setup scripts detect and work around via the `py` launcher.

