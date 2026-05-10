"""FastAPI app — REST + minimal HTML surface.

Surfaces:
  GET  /                — Narrative Board (HTML)
  GET  /narratives/{id} — Narrative Tracker page (HTML)
  GET  /search?q=...    — NL search (HTML), 🤖 may call AI when enabled
  POST /api/follow      — Follow a narrative
  POST /api/unfollow    — Unfollow a narrative
  GET  /api/narratives  — JSON list (for clients/scripts)

Auth in V1 is single-user ("local"); replace with proper user system in V2.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import __version__, ai
from ..config import get_settings
from ..models import LifecycleStage
from ..store import NarrativeRepo, StateChangeRepo, UserRepo, get_session, init_db


WEB_DIR = Path(__file__).resolve().parent.parent / "web"
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))


def create_app() -> FastAPI:
    settings = get_settings()
    init_db()

    app = FastAPI(title="NarrativeFlow", version=__version__)
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

    # ----------------------------------------------------------- HTML
    @app.get("/", response_class=HTMLResponse)
    def board(request: Request):
        with get_session() as session:
            n_repo = NarrativeRepo(session)
            u_repo = UserRepo(session)
            user = u_repo.get_or_create_local()
            followed = u_repo.followed_narratives(user)

            grouped: dict[str, list] = {s.value: [] for s in LifecycleStage}
            for n in n_repo.list_active(limit=200):
                grouped[n.lifecycle_stage].append(n)

            return templates.TemplateResponse(
                request,
                "board.html",
                {
                    "version": __version__,
                    "ai_enabled": ai.ai_enabled(),
                    "user": user,
                    "followed_ids": {n.id for n in followed},
                    "grouped": grouped,
                    "stage_order": [s.value for s in LifecycleStage],
                },
            )

    @app.get("/narratives/{narrative_id}", response_class=HTMLResponse)
    def narrative_page(narrative_id: str, request: Request):
        with get_session() as session:
            n_repo = NarrativeRepo(session)
            sc_repo = StateChangeRepo(session)
            u_repo = UserRepo(session)

            n = n_repo.get(narrative_id) or n_repo.get_by_slug(narrative_id)
            if not n:
                raise HTTPException(status_code=404, detail="narrative not found")
            user = u_repo.get_or_create_local()
            following = any(f.narrative_id == n.id for f in user.follows)
            return templates.TemplateResponse(
                request,
                "narrative.html",
                {
                    "version": __version__,
                    "ai_enabled": ai.ai_enabled(),
                    "n": n,
                    "contents": n_repo.contents_for(n.id, limit=20),
                    "state_changes": sc_repo.recent_for(n.id, limit=20),
                    "following": following,
                },
            )

    @app.get("/search", response_class=HTMLResponse)
    def search(request: Request, q: str = Query(default="", min_length=0)):
        results: list = []
        match: Optional[dict] = None
        with get_session() as session:
            n_repo = NarrativeRepo(session)
            if q.strip():
                results = n_repo.search(q, limit=20)
                # 🤖 If AI is enabled and lexical search yields nothing strong,
                # ask the model whether to match an existing narrative or seed
                # a new one. Pure UX nicety; pipeline stage 3 is the real path.
                if ai.ai_enabled():
                    candidates = [
                        {"id": n.id, "title": n.title, "one_liner": n.one_liner,
                         "centroid_terms": n.centroid_terms}
                        for n in n_repo.list_active(limit=30)
                    ]
                    match = ai.match_query_to_narrative(query=q, candidates=candidates)
            return templates.TemplateResponse(
                request,
                "search.html",
                {
                    "version": __version__,
                    "ai_enabled": ai.ai_enabled(),
                    "q": q,
                    "results": results,
                    "match": match,
                },
            )

    # --------------------------------------------------------- actions
    @app.post("/follow", response_class=RedirectResponse)
    def follow(narrative_id: str = Form(...)):
        with get_session() as session:
            n = NarrativeRepo(session).get(narrative_id)
            if not n:
                raise HTTPException(status_code=404)
            user = UserRepo(session).get_or_create_local()
            UserRepo(session).follow(user, n)
        return RedirectResponse(url=f"/narratives/{narrative_id}", status_code=303)

    @app.post("/unfollow", response_class=RedirectResponse)
    def unfollow(narrative_id: str = Form(...)):
        with get_session() as session:
            n = NarrativeRepo(session).get(narrative_id)
            if not n:
                raise HTTPException(status_code=404)
            user = UserRepo(session).get_or_create_local()
            UserRepo(session).unfollow(user, n)
        return RedirectResponse(url=f"/narratives/{narrative_id}", status_code=303)

    # ---------------------------------------------------------- JSON
    @app.get("/api/narratives", response_class=JSONResponse)
    def api_narratives(stage: Optional[str] = None, limit: int = 100):
        with get_session() as session:
            repo = NarrativeRepo(session)
            items = repo.list_by_lifecycle(stage, limit=limit) if stage else repo.list_active(limit=limit)
            return [_serialize(n) for n in items]

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__, "ai_enabled": ai.ai_enabled()}

    return app


def _serialize(n) -> dict:
    return {
        "id": n.id,
        "title": n.title,
        "slug": n.slug,
        "one_liner": n.one_liner,
        "lifecycle_stage": n.lifecycle_stage,
        "heat_score": n.heat_score,
        "ticker_map": n.ticker_map,
        "causal_chain": n.causal_chain,
        "catalysts": n.catalysts,
        "key_evidence": n.key_evidence,
        "counter_narrative": n.counter_narrative,
        "last_updated": n.last_updated.isoformat() if n.last_updated else None,
    }


# Module-level instance so `uvicorn narrativeflow.api.main:app` works.
app = create_app()
