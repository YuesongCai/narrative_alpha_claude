# NarrativeFlow

> Narrative-driven investment intelligence — turn fragmented public news flow
> into structured, lifecycle-staged narrative trackers with ticker maps,
> catalysts, and exit signals.

NarrativeFlow ingests public news/research feeds, deduplicates and filters
them, clusters items into market narratives, and synthesizes a structured
**Narrative Tracker** for each one. State changes (new catalyst, lifecycle
shift, ticker rotation, exit signal) drive notifications — never news-feed
firehose.

This repo is the V1 minimal-but-scalable implementation per the
[NarrativeFlow PRD v1.0](docs/PRD.md *(not bundled)*). It runs end-to-end on
a fresh checkout in under a minute.

---

## 1. Quick start (60 seconds)

```bash
# 1. install
pip install -e .

# 2. initialize SQLite store + local user
narrativeflow init

# 3. load the bundled seed corpus (10 real sample items + 2 noise items)
narrativeflow seed

# 4. inspect the board in your terminal
narrativeflow board

# 5. or open the web UI
narrativeflow serve
# → http://127.0.0.1:8000
```

To pull from real public sources instead of the seed corpus:

```bash
narrativeflow ingest                     # pull from all configured public feeds
narrativeflow synthesize                 # filter + tag + synthesize
narrativeflow board                      # see results
```

To enable the four AI touchpoints, drop your key into `.env` (see
[`.env.example`](.env.example)):

```bash
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=sk-ant-...
narrativeflow synthesize --force         # re-synthesize with the LLM
```

Without an API key the system stays fully runnable using deterministic
heuristics; the web UI shows a 🤖 **AI disabled (heuristic mode)** badge.

---

## 2. Architecture

```
                                                 ┌─────────────────┐
                                                 │   FastAPI / Web │
                                                 │  /board /search │
                                                 │  /api/narratives│
                                                 └────────▲────────┘
                                                          │
┌────────────┐   ┌───────────┐   ┌───────────┐   ┌────────┴────────┐
│  Sources   │──▶│   Pipeline│──▶│  Store    │──▶│   Notify        │
│  (public)  │   │ (4 stages)│   │ (SQLA)    │   │  Telegram, ...  │
└────────────┘   └─────┬─────┘   └───────────┘   └─────────────────┘
                       │
                       ▼
                 ┌──────────┐  ← 🤖 every AI call goes through here
                 │   ai/    │
                 │ Anthropic│
                 │   SDK    │
                 └──────────┘
```

### Layer responsibilities

| Layer | Module | What it owns |
|-------|--------|--------------|
| **Config** | `narrativeflow/config.py` | Env-based settings via `pydantic-settings` |
| **Models** | `narrativeflow/models/` | SQLAlchemy ORM: `RawContent`, `Narrative`, `NarrativeContent`, `User`, `UserFollow`, `StateChange` |
| **Store** | `narrativeflow/store/` | DB engine + repositories — the only place SQLAlchemy queries live |
| **Sources** | `narrativeflow/sources/` | Pluggable `SourceAdapter` ABC + concrete adapters (RSS, SEC EDGAR, Hacker News, manual) |
| **AI** | `narrativeflow/ai/` | 🤖 Anthropic client wrapper, prompt templates, four high-level AI tasks |
| **Pipeline** | `narrativeflow/pipeline/` | Four ordered stages: `ingest → filter → tag → synthesize` + lifecycle scoring |
| **API** | `narrativeflow/api/` | FastAPI app + Jinja templates (board / narrative / search) |
| **Notify** | `narrativeflow/notify/` | `NotificationChannel` ABC + Telegram + no-op + dispatcher (state-change driven) |
| **Scheduler** | `narrativeflow/scheduler/` | In-process loop that runs pipeline + dispatch periodically |
| **CLI** | `narrativeflow/cli.py` | Click-based operator commands |

### Key design decisions for scale

- **Repository pattern** isolates SQL from the rest of the code, so swapping
  SQLite → Postgres is one change in `store/db.py` (set `DATABASE_URL`).
- **Source adapters are plug-ins.** Adding a new public feed is: write one
  class that subclasses `SourceAdapter`, drop a YAML entry in
  [`narrativeflow/data/source_config.yaml`](narrativeflow/data/source_config.yaml) — no other change.
- **Notification channels are plug-ins.** Telegram is one subclass of
  `NotificationChannel`; Slack / WeChat-OA / Email are 30 lines each.
- **AI is one folder.** Every AI call lives in `narrativeflow/ai/`. To swap
  provider, change one wrapper. To strip AI entirely, the heuristic fallbacks
  already produce a working pipeline.
- **Each pipeline stage is independent.** They communicate only through DB
  state, so they can be parallelized, queued, or distributed when scale
  demands it. V1 runs them sequentially in one process.

---

## 3. 🤖 AI API Usage — exactly four touchpoints

Every place this codebase calls the Claude API is enumerated here. They all
live in `narrativeflow/ai/` and every call has a deterministic fallback.

| # | Pipeline stage | Function | Module:line | Model | Purpose |
|---|----|----------|-------------|-------|---------|
| **1** | Stage 2 — noise filter | `classify_noise` | [`narrativeflow/ai/tasks.py`](narrativeflow/ai/tasks.py) | `claude-sonnet-4-6` (fast) | Decide whether a piece of content is investable signal or noise (ad / horoscope / off-topic). |
| **2** | Stage 3 — narrative tagging | `tag_to_narratives` | [`narrativeflow/ai/tasks.py`](narrativeflow/ai/tasks.py) | `claude-sonnet-4-6` (fast) | Match a content item to existing narrative(s); if nothing fits, propose a new narrative title + one-liner. |
| **3** | Stage 4 — synthesis | `synthesize_narrative` | [`narrativeflow/ai/tasks.py`](narrativeflow/ai/tasks.py) | `claude-opus-4-7` (deep) | Produce the full Narrative Tracker: one_liner, causal_chain, ticker_map, catalysts, key_evidence, counter_narrative. |
| **4** | UX — natural-language search | `match_query_to_narrative` | [`narrativeflow/ai/tasks.py`](narrativeflow/ai/tasks.py) | `claude-sonnet-4-6` (fast) | Resolve a user's NL query (e.g. `核电`, `AI infra`) to one of the existing narratives, or recommend creating a new one. |

**Cost controls:**

- The system prompt for each task is sent with `cache_control: ephemeral`
  → repeated calls hit Anthropic's prompt cache (~70% token savings on
  repeated traffic).
- Synthesis (Stage 4) only re-runs when new content has been tagged to the
  narrative since `last_synthesized_at`. Force a refresh with
  `narrativeflow synthesize --force`.

**Heuristic fallbacks** (used when `ANTHROPIC_API_KEY` is empty):

1. Noise filter: keyword blocklist (`sponsored`, `horoscope`, …) + investable-
   keyword count.
2. Tagging: TF-IDF-style lexical overlap between content tokens and each
   narrative's centroid terms.
3. Synthesis: template causal chain + extracted parenthetical / `$TICKER`
   tickers + a footer noting AI was disabled.
4. NL search: substring + token-overlap ranking.

---

## 4. Narrative Tracker schema

The atomic unit of the product. Persisted as a row in `narratives` with JSON
columns for the structured fields.

| Field | Type | Description |
|---|---|---|
| `id` | UUID | Primary key |
| `source_type` | enum | `user_created` · `editor_pick` · `market_derived` · `community_surfaced` |
| `title` | str | Short narrative name |
| `slug` | str | URL slug |
| `one_liner` | str | One-sentence thesis |
| `causal_chain` | str[] | Step-by-step logic from cause to investable consequence |
| `lifecycle_stage` | enum | `emerging` → `accelerating` → `consensus` → `crowded` → `fading` |
| `heat_score` | float 0–1 | Composite of mention velocity, source diversity, recency |
| `ticker_map` | obj | `{main_trade, second_derivative, etf_proxy, hk_mirror}`, each a list of `{ticker, name, thesis}` |
| `catalysts` | obj[] | `{date_hint, event, impact}` |
| `key_evidence` | obj[] | `{claim, source_index, date}` |
| `counter_narrative` | str | The strongest bear case |
| `centroid_terms` | str[] | Top lexical terms (used by heuristic tagger) |
| `state_changes` | rel | Audit log feeding the notification dispatcher |

---

## 5. Public sources shipped by default

Defined in [`narrativeflow/data/source_config.yaml`](narrativeflow/data/source_config.yaml). All free, all public, no API keys required.

| Adapter | Source | URL |
|---|---|---|
| `rss` | BBC Business | `feeds.bbci.co.uk/news/business/rss.xml` |
| `rss` | Yahoo Finance | `finance.yahoo.com/news/rssindex` |
| `rss` | FT — Companies | `ft.com/companies?format=rss` |
| `rss` | CNBC Finance | `search.cnbc.com/...?id=10000664` |
| `rss` | MarketWatch | `feeds.marketwatch.com/marketwatch/topstories/` |
| `rss` | TechCrunch | `techcrunch.com/feed/` |
| `hackernews` | HN front page | Firebase API |
| `sec_edgar` | SEC EDGAR 8-K filings | `sec.gov/cgi-bin/browse-edgar` |

Adding a new source: add a `kind: rss` block with a `key`, `name`, `url`.
For non-RSS sources, write a 30-line subclass of
[`SourceAdapter`](narrativeflow/sources/base.py) and register it in
[`narrativeflow/sources/registry.py`](narrativeflow/sources/registry.py).

---

## 6. CLI cheat sheet

```bash
narrativeflow init                  # create DB tables + local user
narrativeflow ingest [--source K]   # pull from configured public feeds
narrativeflow synthesize [--force]  # filter + tag + synthesize (no ingest)
narrativeflow pipeline              # full ingest + synthesize
narrativeflow submit --title ... --body ... --url ...    # paste in a source
narrativeflow seed                  # load bundled offline demo content
narrativeflow board                 # print board to terminal
narrativeflow show <id|slug>        # pretty-print one narrative
narrativeflow follow <id>           # follow a narrative as the local user
narrativeflow notify                # dispatch pending state-change alerts
narrativeflow serve                 # start the FastAPI web server
narrativeflow scheduler --interval 600 [--once]   # run periodic loop
```

---

## 7. Testing

```bash
pip install -e '.[dev]'
pytest                               # 17 tests; all run fully offline
```

Tests use isolated SQLite per-test (see `tests/conftest.py`) and force the AI
client into heuristic mode so they never depend on a network or API key.

---

## 8. Roadmap to V2

The architecture is the way it is so the following V2 work doesn't require
rewrites:

- **Postgres + pgvector** for narrative similarity search — swap `DATABASE_URL`
  + add a `pgvector` column on `Narrative.centroid_terms`.
- **Async source ingest** — the `SourceAdapter.fetch` interface stays sync,
  but a thin async wrapper can run them concurrently.
- **APScheduler / Cloud cron** — replace the in-process loop in
  `narrativeflow/scheduler/jobs.py` without touching the pipeline.
- **Auth + multi-user** — `User`/`UserFollow` are already modeled; add an
  auth provider in `api/`.
- **Editor Pick channel** — backed by an admin-only `source_type=editor_pick`
  flag on `Narrative` plus a curator UI.

---

## 9. License

Proprietary. Not open-source. Alpha targets are hypotheses, not investment
advice.
