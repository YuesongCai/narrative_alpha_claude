"""NarrativeFlow CLI.

    narrativeflow init               — create DB tables + seed local user
    narrativeflow ingest [--source]  — pull from configured public sources
    narrativeflow synthesize         — run filter → tag → synthesize
    narrativeflow pipeline           — full run (ingest + synthesize)
    narrativeflow submit             — manually submit a content item
    narrativeflow notify             — dispatch pending state-change alerts
    narrativeflow follow / unfollow  — manage local user follow set
    narrativeflow board              — print board to terminal
    narrativeflow show <id|slug>     — pretty-print a narrative
    narrativeflow seed               — load bundled seed content for demo
    narrativeflow serve              — start the FastAPI web server
    narrativeflow scheduler          — run the periodic loop
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import click

from . import __version__
from .config import get_settings
from .models import Narrative
from .notify import dispatch_pending
from .pipeline import run_pipeline
from .pipeline.ingest import ingest_from
from .scheduler import run_loop
from .sources import default_registry
from .sources.manual import ManualSource
from .store import (
    NarrativeRepo,
    StateChangeRepo,
    UserRepo,
    get_session,
    init_db,
)


def _setup_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    )


@click.group(help="NarrativeFlow — narrative-driven investment intelligence.")
@click.version_option(__version__, prog_name="narrativeflow")
def cli() -> None:
    _setup_logging()


# ----------------------------------------------------------------- init
@cli.command()
def init() -> None:
    """Create DB tables and the default local user."""
    init_db()
    with get_session() as session:
        UserRepo(session).get_or_create_local()
    click.echo("✓ database initialized")


# --------------------------------------------------------------- ingest
@cli.command()
@click.option("--source", "source_keys", multiple=True, help="Limit to specific source keys (default: all).")
def ingest(source_keys: tuple[str, ...]) -> None:
    """Pull content from configured public sources."""
    init_db()
    registry = default_registry()
    if source_keys:
        adapters = [a for a in registry.all() if a.key in source_keys]
        if not adapters:
            click.echo(f"no matching sources. configured: {registry.keys()}", err=True)
            sys.exit(1)
    else:
        adapters = registry.all()
    counts = ingest_from(adapters)
    for k, v in counts.items():
        click.echo(f"  {k}: +{v}")


# -------------------------------------------------------- synth/pipeline
@cli.command()
@click.option("--force", is_flag=True, help="Re-synthesize even when no new content.")
def synthesize(force: bool) -> None:
    """Run filter → tag → synthesize stages without touching ingest."""
    init_db()
    report = run_pipeline(skip_ingest=True, force_synthesis=force)
    click.echo(report.summary())


@cli.command()
@click.option("--source", "source_keys", multiple=True)
@click.option("--force", is_flag=True)
def pipeline(source_keys: tuple[str, ...], force: bool) -> None:
    """Full pipeline: ingest + filter + tag + synthesize."""
    init_db()
    registry = default_registry()
    adapters = [a for a in registry.all() if a.key in source_keys] if source_keys else None
    report = run_pipeline(adapters=adapters, force_synthesis=force)
    click.echo(report.summary())


# ---------------------------------------------------------------- submit
@cli.command()
@click.option("--title", required=True)
@click.option("--body", required=True)
@click.option("--url", default=None)
@click.option("--author", default="manual")
def submit(title: str, body: str, url: str | None, author: str) -> None:
    """Submit a single piece of content manually (PDF text, pasted note, etc.)."""
    init_db()
    adapter = ManualSource(title=title, body=body, url=url, author=author)
    counts = ingest_from([adapter])
    click.echo(f"submitted: {counts}")
    report = run_pipeline(skip_ingest=True)
    click.echo(report.summary())


# ----------------------------------------------------------------- notify
@cli.command()
def notify() -> None:
    """Dispatch any pending state-change notifications."""
    init_db()
    delivered = dispatch_pending()
    click.echo(f"delivered={delivered}")


# ------------------------------------------------------------- follow set
@cli.command()
@click.argument("narrative_id")
def follow(narrative_id: str) -> None:
    """Follow a narrative as the local user."""
    init_db()
    with get_session() as session:
        n = NarrativeRepo(session).get(narrative_id) or NarrativeRepo(session).get_by_slug(narrative_id)
        if not n:
            click.echo("narrative not found", err=True)
            sys.exit(1)
        u = UserRepo(session).get_or_create_local()
        UserRepo(session).follow(u, n)
        click.echo(f"following: {n.title}")


@cli.command()
@click.argument("narrative_id")
def unfollow(narrative_id: str) -> None:
    """Unfollow a narrative."""
    init_db()
    with get_session() as session:
        n = NarrativeRepo(session).get(narrative_id) or NarrativeRepo(session).get_by_slug(narrative_id)
        if not n:
            click.echo("narrative not found", err=True)
            sys.exit(1)
        u = UserRepo(session).get_or_create_local()
        UserRepo(session).unfollow(u, n)
        click.echo(f"unfollowed: {n.title}")


# ----------------------------------------------------------------- board
@cli.command()
def board() -> None:
    """Print the narrative board to the terminal."""
    init_db()
    with get_session() as session:
        repo = NarrativeRepo(session)
        narratives = repo.list_active(limit=50)
        if not narratives:
            click.echo("no narratives yet — try `narrativeflow pipeline`")
            return
        click.echo(f"NARRATIVE BOARD ({len(narratives)} narratives)")
        click.echo("=" * 78)
        for n in narratives:
            tickers = " ".join(t.get("ticker", "?") for t in (n.ticker_map.get("main_trade") or []))[:40]
            click.echo(
                f"  [{n.lifecycle_stage:13}] heat {n.heat_score:5.2f}  "
                f"{n.title[:50]:50}  {tickers}"
            )


@cli.command()
@click.argument("identifier")
def show(identifier: str) -> None:
    """Pretty-print one narrative."""
    init_db()
    with get_session() as session:
        repo = NarrativeRepo(session)
        n = repo.get(identifier) or repo.get_by_slug(identifier)
        if not n:
            click.echo("not found", err=True)
            sys.exit(1)
        click.echo(f"\n[{n.lifecycle_stage}] {n.title}")
        click.echo(f"  {n.one_liner}")
        click.echo(f"  heat={n.heat_score:.2f}  source_type={n.source_type}  "
                   f"last_updated={n.last_updated.strftime('%Y-%m-%d %H:%M')}")
        if n.causal_chain:
            click.echo("\n  Causal chain:")
            for step in n.causal_chain:
                click.echo(f"    → {step}")
        for label, key in (("Main", "main_trade"), ("Second", "second_derivative"),
                           ("ETF", "etf_proxy"), ("HK", "hk_mirror")):
            bucket = n.ticker_map.get(key) or []
            if bucket:
                click.echo(f"\n  {label} trade:")
                for t in bucket:
                    click.echo(f"    {t.get('ticker','?'):6}  {t.get('name','')[:40]:40}  {t.get('thesis','')[:80]}")
        if n.catalysts:
            click.echo("\n  Catalysts:")
            for c in n.catalysts:
                click.echo(f"    {c.get('date_hint','TBD'):10}  {c.get('event','')}  ({c.get('impact','')})")
        if n.counter_narrative:
            click.echo("\n  Counter-narrative:")
            click.echo(f"    {n.counter_narrative}")


# ------------------------------------------------------------------ seed
@cli.command()
def seed() -> None:
    """Load the bundled seed content (for demo without network)."""
    init_db()
    seed_path = Path(__file__).parent / "data" / "seed_content.json"
    if not seed_path.exists():
        click.echo("seed file missing", err=True)
        sys.exit(1)
    with seed_path.open("r", encoding="utf-8") as f:
        items = json.load(f)
    adapters = []
    for it in items:
        adapter = ManualSource(
            title=it["title"],
            body=it["body"],
            url=it.get("url"),
            author=it.get("author", "seed"),
            external_id=it.get("external_id"),
            published_at=datetime.fromisoformat(it["published_at"]) if it.get("published_at") else None,
        )
        adapter.key = "seed"
        adapter.name = "Seed corpus"
        adapters.append(adapter)
    counts = ingest_from(adapters)
    total = sum(counts.values())
    click.echo(f"loaded {total} seed items")
    report = run_pipeline(skip_ingest=True)
    click.echo(report.summary())


# ------------------------------------------------------------------ serve
@cli.command()
@click.option("--reload", is_flag=True, help="Auto-reload on code changes (dev).")
def serve(reload: bool) -> None:
    """Run the FastAPI web server."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "narrativeflow.api.main:app",
        host=settings.host,
        port=settings.port,
        reload=reload,
    )


# -------------------------------------------------------------- scheduler
@cli.command()
@click.option("--interval", default=600, help="Seconds between iterations.")
@click.option("--once", is_flag=True, help="Run a single iteration and exit.")
def scheduler(interval: int, once: bool) -> None:
    """Run the periodic ingest+synthesize+notify loop."""
    init_db()
    run_loop(interval_seconds=interval, run_once=once)


if __name__ == "__main__":  # pragma: no cover
    cli()
