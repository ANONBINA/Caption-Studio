# Caption Studio

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

```bash
pip install -e ".[web]"          # editable install, incl. web dependencies

# Web app (recommended) — http://localhost:8000
caption-studio serve

# ...or straight from the command line
caption-studio caption "Malcolm In The Middle"

# (CLI-only install, no web app: pip install -e .)
# (still works too: python -m caption_studio.cli ...)
```

The web app is the fastest route: search your library, click a title, get a
caption, copy it. No setup, no API key required.

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

---

## Development

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
web/index.html   single-file UI (no CDNs, works offline)
tests/           pytest suite: config, catalog folding, captions, store
config.example.json   template config for fresh clones
data/            catalogs + enriched.json + overrides.json (git-ignored)
out/            generated captions (git-ignored)
.tmdb_cache/     cached TMDB responses (git-ignored)
```

## Requirements

Python 3.9+. `pip install -e ".[web]"` pulls in `fastapi`, `uvicorn` and
`python-multipart` for the web app (`requirements.txt` still works for a
plain `pip install -r`). The CLI's `caption`, `batch`, `search` and `stats`
commands run on the standard library alone — install FastAPI only if you want
the web app.
