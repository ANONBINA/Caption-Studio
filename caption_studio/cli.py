"""Command line interface for Caption Studio.

    python -m caption_studio.cli stats
    python -m caption_studio.cli search "breaking"
    python -m caption_studio.cli show "Breaking Bad"
    python -m caption_studio.cli caption "Breaking Bad" --copy
    python -m caption_studio.cli batch --all --out out/ --format txt
    python -m caption_studio.cli enrich "Breaking Bad" --tmdb-key KEY
    python -m caption_studio.cli dupes
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from .caption import CaptionOptions, build_caption
from .config import Config
from .export import write_batch_csv, write_caption, write_index_html
from .models import Title
from .store import Store
from .tmdb import TMDBClient, TMDBError


def _store(args) -> Store:
    return Store(getattr(args, "root", None) or None)


def _resolve(store: Store, query: str) -> Title:
    title = store.find_by_name(query)
    if title is None:
        hits = store.library.find(query, limit=5)
        if not hits:
            sys.exit(f"No title matching {query!r}. Try: python -m caption_studio.cli search {query!r}")
        if len(hits) > 1:
            print("Multiple matches:", ", ".join(h.name for h in hits), file=sys.stderr)
        title = hits[0]
    return title


def _options(args, cfg: Config) -> CaptionOptions:
    return CaptionOptions.from_dict({
        "variant": getattr(args, "variant", 0),
        "style": getattr(args, "style", None) or cfg.get("default_style"),
        "length": getattr(args, "length", None) or cfg.get("default_length"),
        "expect_count": getattr(args, "bullets", 4),
    }, cfg)


def _print_caption(title: Title, caption, show_warnings: bool = True) -> None:
    print(caption.text)
    print()
    print(f"[ {caption.char_count} chars ]")
    if show_warnings and caption.warnings:
        print("[ review: ]")
        for w in caption.warnings:
            print(f"  - {w}")


# ---------------------------------------------------------------------------
def cmd_stats(args) -> int:
    store = _store(args)
    s = store.stats()
    print(json.dumps(s, indent=2, ensure_ascii=False))
    return 0


def cmd_search(args) -> int:
    store = _store(args)
    results, total = store.library.search(
        query=args.query, kind=args.kind or "", genre=args.genre or "",
        resolution=args.resolution or "", limit=args.limit)
    if not results:
        print("Nothing found.")
        return 1
    for t in results:
        specs = []
        if t.is_series:
            specs.append(f"{t.seasons}s/{t.episodes}ep")
        if t.runtime_min:
            specs.append(f"{t.runtime_min}m")
        specs.append(t.resolution_label or "—")
        print(f"{t.id}  {t.kind_label:<6} {t.name} ({t.year_label})  "
              f"[{' | '.join(t.genres) or '—'}]  {', '.join(specs)}")
    print(f"\n{total} match(es), showing {len(results)}.")
    return 0


def cmd_show(args) -> int:
    store = _store(args)
    title = _resolve(store, args.query)
    data = title.to_dict()
    data["files"] = data["files"][:3]
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


def cmd_caption(args) -> int:
    store = _store(args)
    cfg = store.config
    title = _resolve(store, args.query)
    caption = build_caption(title, cfg, _options(args, cfg))
    if args.out:
        paths = write_caption(caption, args.out, args.format, title, cfg.brand)
        for p in paths:
            print(f"wrote {p}")
    if not args.quiet:
        if args.out:
            print()
        _print_caption(title, caption, show_warnings=not args.no_warnings)
    return 0


def cmd_batch(args) -> int:
    store = _store(args)
    cfg = store.config
    titles: List[Title] = []
    if args.ids:
        wanted = set(args.ids)
        titles = [t for t in store.library.titles if t.id in wanted]
    elif args.newest:
        titles = sorted(store.library.titles, key=lambda t: -(t.year or 0))[:args.limit]
    else:
        # --all, or a --query (which may be empty) narrowed by --kind/--genre.
        results, _ = store.library.search(query=args.query or "", kind=args.kind or "",
                                          limit=args.limit if not args.all else 10 ** 6)
        titles = results

    if not titles:
        print("Nothing to do.")
        return 1

    out_dir = args.out or os.path.join(store.root, "out")
    pairs = []
    for t in titles:
        cap = build_caption(t, cfg, _options(args, cfg))
        pairs.append((t, cap))
        write_caption(cap, out_dir, args.format, t, cfg.brand)

    csv_path = write_batch_csv(pairs, os.path.join(out_dir, "captions.csv"))
    html_path = write_index_html(pairs, os.path.join(out_dir, "index.html"), cfg.brand)
    print(f"Generated {len(pairs)} captions into {out_dir}")
    print(f"  {csv_path}")
    print(f"  {html_path}")
    needs_review = sum(1 for _, c in pairs if c.warnings)
    if needs_review:
        print(f"  {needs_review} caption(s) flagged for review (see captions.csv column 'warnings')")
    return 0


def cmd_enrich(args) -> int:
    store = _store(args)
    cfg = store.config
    key = args.tmdb_key or cfg.get("tmdb_api_key") or os.environ.get("TMDB_API_KEY")
    if not key:
        print("No TMDB key. Set tmdb_api_key in config.json, pass --tmdb-key, "
              "or export TMDB_API_KEY.  Get one free at https://www.themoviedb.org/settings/api")
        return 1
    client = TMDBClient(key, cfg.get("tmdb_language", "en-US"))

    targets: List[Title] = []
    if args.all:
        targets = store.library.titles
    elif args.query:
        targets = [_resolve(store, args.query)]
    else:
        print("Give me a title, or use --all")
        return 1

    if args.all:
        targets = [t for t in targets if not t.enriched][:args.limit]

    ok = fail = 0
    for t in targets:
        try:
            result = client.enrich(t, with_trailer=cfg.get("tmdb_auto_trailer", True))
        except TMDBError as exc:
            print(f"  ✗ {t.name}: {exc}")
            fail += 1
            continue
        store.save_enriched(t)
        print(f"  ✓ {t.name} → {result['matched']} [{', '.join(result['changed']) or 'nothing new'}]")
        ok += 1
    print(f"\nEnriched {ok}, failed {fail}.")
    return 0 if ok else 1


def cmd_dupes(args) -> int:
    store = _store(args)
    pairs = store.duplicates(cutoff=args.cutoff)
    if not pairs:
        print("No likely duplicates.")
        return 0
    for p in pairs:
        print(f"{p['score']:.3f}  {p['a_name']}  <->  {p['b_name']}   "
              f"({p['a']}, {p['b']})")
    print("\nMerge with:  python -m caption_studio.cli merge <keep_id> <merge_id>")
    return 0


def cmd_merge(args) -> int:
    store = _store(args)
    store.merge(args.keep, args.merge)
    print(f"Merged {args.merge} into {args.keep} (saved to config.json merge_rules).")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    from .app import create_app
    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="caption-studio",
        description="Generate Plugent-style promo captions from your media catalog.")
    parser.add_argument("--root", default=None, help="project root (default: auto)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("stats", help="library summary")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("search", help="search the library")
    p.add_argument("query", nargs="?", default="")
    p.add_argument("--kind", choices=["movie", "series"], default="")
    p.add_argument("--genre", default="")
    p.add_argument("--resolution", default="")
    p.add_argument("--limit", type=int, default=40)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("show", help="dump everything known about a title")
    p.add_argument("query")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("caption", help="generate one caption")
    p.add_argument("query")
    p.add_argument("--variant", type=int, default=0, help="wording variant (0,1,2...)")
    p.add_argument("--style", choices=["classic", "extended"])
    p.add_argument("--length", choices=["full", "short", "teaser"])
    p.add_argument("--bullets", type=int, default=4)
    p.add_argument("--out", default="", help="directory to write files into")
    p.add_argument("--format", nargs="*", default=["txt"], help="txt md html json")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--no-warnings", action="store_true")
    p.set_defaults(func=cmd_caption)

    p = sub.add_parser("batch", help="generate many captions")
    p.add_argument("--all", action="store_true")
    p.add_argument("--query", default="")
    p.add_argument("--ids", nargs="*", default=[])
    p.add_argument("--newest", action="store_true")
    p.add_argument("--kind", choices=["movie", "series"], default="")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--out", default="")
    p.add_argument("--format", nargs="*", default=["txt"])
    p.add_argument("--variant", type=int, default=0)
    p.add_argument("--style", choices=["classic", "extended"])
    p.add_argument("--length", choices=["full", "short", "teaser"])
    p.add_argument("--bullets", type=int, default=4)
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("enrich", help="pull synopsis/cast/rating/trailer from TMDB")
    p.add_argument("query", nargs="?", default="")
    p.add_argument("--all", action="store_true")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--tmdb-key", default="")
    p.set_defaults(func=cmd_enrich)

    p = sub.add_parser("dupes", help="find likely duplicate titles")
    p.add_argument("--cutoff", type=float, default=0.9)
    p.set_defaults(func=cmd_dupes)

    p = sub.add_parser("merge", help="merge two title ids")
    p.add_argument("keep")
    p.add_argument("merge")
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("serve", help="run the web app")
<<<<<<< HEAD
    p.add_argument("--host", default="0.0.0.0")
=======
    p.add_argument("--host", default="127.0.0.1")
>>>>>>> origin/master
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
<<<<<<< HEAD
=======

>>>>>>> origin/master
