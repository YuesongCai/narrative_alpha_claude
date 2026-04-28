"""Command-line interface.

Subcommands:
  init        — bootstrap the store with the bundled seed corpus.
  ingest-rss  — pull entries from an RSS feed into the store.
  submit      — submit a manual source (PDF text / pasted content).
  pipeline    — run the daily pipeline (extract → cluster → score → map → digest).
  digest      — render today's digest to terminal and/or HTML.
  show        — inspect a single narrative.
  metrics     — print success-metrics readout.

`narrative-alpha pipeline && narrative-alpha digest --html out.html`
is the canonical "daily run".
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .digest import render_html, render_terminal
from .ingest import ingest_rss, load_seed_file, submit_manual
from .models import Stage
from .pipeline import run_pipeline
from .store import Store
from .validate import compute_track_record

DEFAULT_SEED = Path(__file__).parent.parent / "data" / "seed_sources.json"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="narrative-alpha", description="Narrative Alpha CLI")
    p.add_argument("--data-dir", default=None, help="path to the JSON state directory (default: ./data)")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--version", action="version", version=f"narrative-alpha {__version__}")

    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", help="bootstrap the store with seed data")
    sp.add_argument("--seed", default=str(DEFAULT_SEED), help="path to a seed JSON file")
    sp.add_argument("--run", action="store_true", help="also run the pipeline after seeding")

    sp = sub.add_parser("ingest-rss", help="pull a feed into the store")
    sp.add_argument("url")
    sp.add_argument("--org", default=None, help="override the publisher name")

    sp = sub.add_parser("submit", help="submit a user-contributed source")
    sp.add_argument("--title", required=True)
    sp.add_argument("--org", required=True)
    sp.add_argument("--body", required=True, help="body text (paste from PDF, etc.)")
    sp.add_argument("--url", default=None)
    sp.add_argument("--tier", type=int, choices=[1, 2, 3], default=None)
    sp.add_argument("--by", default=None, help="who submitted it (user id)")

    sp = sub.add_parser("pipeline", help="run the daily pipeline")
    sp.add_argument("--date", default=None, help="ISO date to use as 'today' (testing)")

    sp = sub.add_parser("digest", help="render today's digest")
    sp.add_argument("--html", default=None, help="write HTML to this path")
    sp.add_argument("--print", dest="print_term", action="store_true", help="print terminal version (default if --html absent)")

    sp = sub.add_parser("show", help="inspect a single narrative")
    sp.add_argument("narrative_id")

    sub.add_parser("metrics", help="print track-record metrics")

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s  %(levelname)-7s  %(message)s")

    store = Store(args.data_dir) if args.data_dir else Store()
    store.load()

    cmd = args.cmd
    if cmd == "init":
        return _cmd_init(store, args)
    if cmd == "ingest-rss":
        return _cmd_ingest_rss(store, args)
    if cmd == "submit":
        return _cmd_submit(store, args)
    if cmd == "pipeline":
        return _cmd_pipeline(store, args)
    if cmd == "digest":
        return _cmd_digest(store, args)
    if cmd == "show":
        return _cmd_show(store, args)
    if cmd == "metrics":
        return _cmd_metrics(store)
    print(f"Unknown command: {cmd}", file=sys.stderr)
    return 2


# --------------------------------------------------------------- handlers
def _cmd_init(store: Store, args) -> int:
    seed_path = Path(args.seed)
    if not seed_path.exists():
        print(f"seed file not found: {seed_path}", file=sys.stderr)
        return 1
    added = load_seed_file(store, seed_path)
    print(f"loaded {len(added)} sources from {seed_path}")
    if args.run:
        report = run_pipeline(store)
        print(report.summary())
    store.save()
    return 0


def _cmd_ingest_rss(store: Store, args) -> int:
    added = ingest_rss(store, args.url, default_org=args.org)
    print(f"added {len(added)} sources from {args.url}")
    store.save()
    return 0


def _cmd_submit(store: Store, args) -> int:
    src = submit_manual(
        store,
        title=args.title,
        body=args.body,
        org=args.org,
        url=args.url,
        tier=args.tier,
        submitted_by=args.by,
    )
    store.save()
    print(f"submitted source: {src.source_id} (tier {src.tier})")
    return 0


def _cmd_pipeline(store: Store, args) -> int:
    today = datetime.fromisoformat(args.date) if args.date else None
    report = run_pipeline(store, today=today)
    store.save()
    print(report.summary())
    return 0


def _cmd_digest(store: Store, args) -> int:
    digest = store.latest_digest()
    if digest is None:
        print("no digest yet — run `narrative-alpha pipeline` first", file=sys.stderr)
        return 1
    if args.html:
        Path(args.html).write_text(render_html(store, digest), encoding="utf-8")
        print(f"wrote {args.html}")
    if args.print_term or not args.html:
        print(render_terminal(store, digest))
    return 0


def _cmd_show(store: Store, args) -> int:
    n = store.narratives.get(args.narrative_id)
    if n is None:
        print(f"narrative not found: {args.narrative_id}", file=sys.stderr)
        return 1
    print(f"[{n.stage}] {n.title}  —  strength {n.strength_score:.1f}")
    print(f"  {n.subtitle}")
    print(f"  first seen: {n.first_seen.date()}    sources: {len(n.source_trail)}")
    print("  source trail:")
    for s in store.sources_for_narrative(n.narrative_id):
        print(f"    [T{s.tier}] {s.published_at.date()}  {s.org}  —  {s.title}")
    print("  alpha targets:")
    for t in n.alpha_targets:
        sign = "+" if t.price_change_pct >= 0 else ""
        print(f"    {t.ticker:8s} {t.kind:13s}  {sign}{t.price_change_pct:5.1f}%   {t.thesis}")
    print(f"  big-cap signal: {n.big_cap_signal}")
    print(f"  key question:   {n.key_question}")
    return 0


def _cmd_metrics(store: Store) -> int:
    rec = compute_track_record(store.active_narratives())
    print(f"narratives flagged Emerging:        {rec.flagged_emerging}")
    print(f"progressed to Strengthening:        {rec.progressed_to_strengthening}")
    print(f"progressed to Consensus:            {rec.progressed_to_consensus}")
    print(f"hit rate:                           {rec.hit_rate_pct:.1f}%")
    print(f"average alpha (positive moves):     {rec.average_alpha_pct:.2f}%")
    print(f"average days to Strengthening:      {rec.average_days_to_strengthening:.1f}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
