"""Narrative clustering.

A claim either joins the most-similar existing narrative (if cosine similarity
to that narrative's centroid clears `JOIN_THRESHOLD`) or seeds a brand-new
narrative. Vectors are TF-IDF over a single combined corpus so similarity is
comparable across narratives; the centroid is recomputed from all member
claims after each join, so it drifts toward the cluster's true theme.

We use TF-IDF (not embeddings) on purpose for V1: zero deps, fully
deterministic, and trivial to debug — every centroid term is human-readable.
The interface (`cluster_claim` returning a narrative_id and a "is_new" flag)
lets us swap in embeddings later without changing pipeline code.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime
from typing import Iterable

from .models import Claim, Narrative, Source, Stage


JOIN_THRESHOLD = 0.08  # below this we seed a new narrative
TOP_TERMS_PER_CLUSTER = 25  # centroid vocabulary cap (for human inspection)
RECONCILE_PASSES = 2  # second pass after initial seeding to absorb late-joining claims

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "of", "to", "in", "on",
    "for", "with", "by", "as", "at", "from", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "it", "its", "this", "that", "these",
    "those", "we", "you", "they", "their", "our", "his", "her", "him", "she",
    "he", "i", "not", "no", "do", "does", "did", "so", "than", "into", "out",
    "over", "under", "more", "most", "less", "least", "very", "much", "many",
    "some", "any", "all", "each", "every", "also", "such", "may", "might",
    "could", "should", "would", "will", "would", "shall", "can", "cannot",
    "while", "where", "when", "what", "which", "who", "whom", "whose", "how",
    "about", "up", "down", "before", "after", "between", "through", "during",
    "above", "below", "across", "against", "among", "off", "again", "further",
    "than", "too", "only", "own", "same", "very", "just", "now", "still",
    "yet", "even", "ever", "never", "however", "therefore", "thus", "hence",
}

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]+")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "") if t.lower() not in _STOPWORDS and len(t) > 2]


# ---------------------------------------------------------------- TF-IDF
def _term_freq(tokens: Iterable[str]) -> dict[str, float]:
    counts = Counter(tokens)
    total = sum(counts.values()) or 1
    return {term: c / total for term, c in counts.items()}


def _document_frequencies(token_lists: list[list[str]]) -> dict[str, int]:
    df: Counter[str] = Counter()
    for toks in token_lists:
        for term in set(toks):
            df[term] += 1
    return df


_IDF_FLOOR = 0.5  # keeps small-corpus clustering well-behaved


def _tf_idf_vector(tokens: list[str], df: dict[str, int], n_docs: int) -> dict[str, float]:
    tf = _term_freq(tokens)
    # Smoothed TF-IDF with an IDF floor — without the floor, terms shared across
    # every document get zero weight, which collapses cosine similarity in tiny
    # corpora. Discriminative power is preserved (rare terms still dominate).
    return {
        term: f * (math.log((1 + n_docs) / (1 + df.get(term, 0))) + _IDF_FLOOR)
        for term, f in tf.items()
        if df.get(term, 0) > 0
    }


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[t] * b[t] for t in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _vector_from_terms(terms: list[str]) -> dict[str, float]:
    """Treat a centroid-term list as a uniform-weight vector."""
    if not terms:
        return {}
    w = 1.0 / math.sqrt(len(terms))
    return {t: w for t in terms}


# -------------------------------------------------------- public API
def cluster_claims(
    claims: list[Claim],
    sources_by_id: dict[str, Source],
    existing: list[Narrative],
) -> tuple[list[Narrative], dict[str, str]]:
    """Assign each claim to an existing or new narrative.

    Returns
    -------
    narratives : list[Narrative]
        All narratives after clustering — both updated existing and new.
    assignments : dict[str, str]
        Mapping of claim_id → narrative_id.
    """
    # Build the global vocabulary across existing narratives + incoming claims
    # so TF-IDF weights are comparable.
    existing_token_lists = [_narrative_tokens(n, sources_by_id) for n in existing]
    incoming_token_lists = [tokenize(_claim_text(c, sources_by_id)) for c in claims]
    df = _document_frequencies(existing_token_lists + incoming_token_lists)
    n_docs = max(1, len(existing_token_lists) + len(incoming_token_lists))

    by_id: dict[str, Narrative] = {n.narrative_id: n for n in existing}
    centroid_vecs: dict[str, dict[str, float]] = {
        n.narrative_id: _tf_idf_vector(toks, df, n_docs)
        for n, toks in zip(existing, existing_token_lists)
    }

    assignments: dict[str, str] = {}
    new_count = 0

    for claim, tokens in zip(claims, incoming_token_lists):
        claim_vec = _tf_idf_vector(tokens, df, n_docs)

        best_id, best_sim = None, 0.0
        for nid, vec in centroid_vecs.items():
            sim = _cosine(claim_vec, vec)
            if sim > best_sim:
                best_id, best_sim = nid, sim

        if best_id is not None and best_sim >= JOIN_THRESHOLD:
            narrative = by_id[best_id]
            _attach(narrative, claim, sources_by_id)
            assignments[claim.claim_id] = best_id
        else:
            new_count += 1
            nid = _new_narrative_id(claim, new_count)
            narrative = _seed_narrative(nid, claim, sources_by_id)
            by_id[nid] = narrative
            assignments[claim.claim_id] = nid

        # Recompute centroid as the TF-IDF vector of all combined text on the
        # narrative; later claims in this batch then see an updated centroid.
        toks = _narrative_tokens(narrative, sources_by_id)
        centroid_vecs[narrative.narrative_id] = _tf_idf_vector(toks, df, n_docs)
        narrative.centroid_terms = _top_terms(narrative, sources_by_id, df, n_docs)

    # Reconciliation pass: a singleton seeded early may not have matched its
    # natural cluster because that cluster only existed as a single document
    # at the time. Now that centroids are richer, retry assignment.
    _merge_singletons(by_id, assignments, sources_by_id, claims, df, n_docs, centroid_vecs)

    # Re-assignment pass: a claim that joined an early-formed cluster A may now
    # match a later-formed cluster B more strongly. Detect and move them.
    _rebalance_weak_attachments(by_id, assignments, sources_by_id, claims, df, n_docs, centroid_vecs)

    return [n for n in by_id.values() if not n.archived], assignments


def _rebalance_weak_attachments(
    by_id: dict[str, Narrative],
    assignments: dict[str, str],
    sources_by_id: dict[str, Source],
    claims: list[Claim],
    df: dict[str, int],
    n_docs: int,
    centroid_vecs: dict[str, dict[str, float]],
) -> None:
    """Re-evaluate each claim against all current centroids; move it if a
    different cluster is materially stronger. Bounded by a few passes to avoid
    oscillation between near-tie assignments.
    """
    claims_by_id = {c.claim_id: c for c in claims}
    for _ in range(3):
        moved = False
        for cid, current_nid in list(assignments.items()):
            current = by_id.get(current_nid)
            claim = claims_by_id.get(cid)
            if not current or not claim or current.archived:
                continue
            claim_tokens = tokenize(_claim_text(claim, sources_by_id))
            claim_vec = _tf_idf_vector(claim_tokens, df, n_docs)

            best_nid, best_sim = current_nid, _cosine(claim_vec, centroid_vecs[current_nid])
            for other_id, other in by_id.items():
                if other_id == current_nid or other.archived:
                    continue
                sim = _cosine(claim_vec, centroid_vecs[other_id])
                if sim > best_sim * 1.25 and sim >= JOIN_THRESHOLD:
                    best_nid, best_sim = other_id, sim

            if best_nid != current_nid:
                # Detach from current, attach to best.
                if cid in current.claim_ids:
                    current.claim_ids.remove(cid)
                if claim.source_id in current.source_trail:
                    current.source_trail.remove(claim.source_id)
                target = by_id[best_nid]
                if cid not in target.claim_ids:
                    target.claim_ids.append(cid)
                if claim.source_id and claim.source_id not in target.source_trail:
                    target.source_trail.append(claim.source_id)
                assignments[cid] = best_nid

                # Refresh centroids on both ends.
                for nid in (current_nid, best_nid):
                    n = by_id[nid]
                    if not n.source_trail:
                        n.archived = True
                        continue
                    toks = _narrative_tokens(n, sources_by_id)
                    centroid_vecs[nid] = _tf_idf_vector(toks, df, n_docs)
                    n.centroid_terms = _top_terms(n, sources_by_id, df, n_docs)
                moved = True
        if not moved:
            break


def _entity_overlap(n: Narrative, claims_by_id: dict[str, Claim]) -> set[str]:
    """Union of all claim entities currently on the narrative (lowercased)."""
    bag: set[str] = set()
    for cid in n.claim_ids:
        c = claims_by_id.get(cid)
        if c:
            for e in c.entities:
                bag.add(e.lower())
    return bag


def _merge_singletons(
    by_id: dict[str, Narrative],
    assignments: dict[str, str],
    sources_by_id: dict[str, Source],
    claims: list[Claim],
    df: dict[str, int],
    n_docs: int,
    centroid_vecs: dict[str, dict[str, float]],
) -> None:
    """Move 1-source narratives into a larger compatible cluster if one exists.

    Combines TF-IDF cosine with an entity-overlap bonus. Short headlines (a
    Reuters one-liner about Vistra) often lack enough vocabulary for cosine
    alone to reach threshold, but if they share named entities with the target
    cluster's claim-set the merge is still defensible.
    """
    claims_by_id = {c.claim_id: c for c in claims}

    def is_singleton(n: Narrative) -> bool:
        return len(n.source_trail) <= 1

    merge_threshold = JOIN_THRESHOLD * 0.6  # softer than the seed threshold

    changed = True
    while changed:
        changed = False
        for nid, n in list(by_id.items()):
            if n.archived or not is_singleton(n):
                continue
            n_entities = _entity_overlap(n, claims_by_id)

            best_id, best_score = None, 0.0
            for other_id, other in by_id.items():
                if other_id == nid or other.archived or len(other.source_trail) < 2:
                    continue
                cos = _cosine(centroid_vecs[nid], centroid_vecs[other_id])
                shared_entities = n_entities & _entity_overlap(other, claims_by_id)
                # Each shared entity adds 0.025 to the similarity score, capped at 0.10.
                bonus = min(0.10, 0.025 * len(shared_entities))
                score = cos + bonus
                if score > best_score:
                    best_id, best_score = other_id, score

            if best_id and best_score >= merge_threshold:
                target = by_id[best_id]
                for cid in n.claim_ids:
                    if cid not in target.claim_ids:
                        target.claim_ids.append(cid)
                    assignments[cid] = best_id
                    claim = claims_by_id.get(cid)
                    if claim and claim.source_id and claim.source_id not in target.source_trail:
                        target.source_trail.append(claim.source_id)
                toks = _narrative_tokens(target, sources_by_id)
                centroid_vecs[best_id] = _tf_idf_vector(toks, df, n_docs)
                target.centroid_terms = _top_terms(target, sources_by_id, df, n_docs)
                n.archived = True
                changed = True


_TITLE_WEIGHT = 2   # repeat title tokens to boost their weight in TF-IDF


def _claim_text(claim: Claim, sources_by_id: dict[str, Source]) -> str:
    src = sources_by_id.get(claim.source_id)
    title = src.title if src else ""
    body = src.body if src else ""
    # Title and thesis_summary express the topic explicitly; weight them up
    # against incidental body mentions (e.g. an article about nuclear PPAs
    # that briefly mentions "AI inference" should not be classed as inference).
    return " ".join([
        (title + " ") * _TITLE_WEIGHT,
        (claim.thesis_summary + " ") * _TITLE_WEIGHT,
        claim.text,
        " ".join(claim.entities),
        body,
    ])


def _narrative_tokens(narrative: Narrative, sources_by_id: dict[str, Source]) -> list[str]:
    parts: list[str] = [(narrative.title + " ") * _TITLE_WEIGHT, (narrative.subtitle + " ") * _TITLE_WEIGHT]
    for sid in narrative.source_trail:
        s = sources_by_id.get(sid)
        if s:
            parts.append((s.title + " ") * _TITLE_WEIGHT)
            parts.append(s.body[:1500])
    return tokenize(" ".join(parts))


def _attach(narrative: Narrative, claim: Claim, sources_by_id: dict[str, Source]) -> None:
    narrative.claim_ids.append(claim.claim_id)
    if claim.source_id and claim.source_id not in narrative.source_trail:
        narrative.source_trail.append(claim.source_id)
    src = sources_by_id.get(claim.source_id)
    if src and src.published_at and src.published_at < narrative.first_seen:
        narrative.first_seen = src.published_at
    narrative.last_updated = datetime.utcnow()


def _recompute_centroid_vec(
    narrative: Narrative,
    by_id: dict[str, Narrative],
    sources_by_id: dict[str, Source],
    df: dict[str, int],
    n_docs: int,
) -> dict[str, float]:
    # Use top centroid terms as the vector; cheap and stable.
    return _vector_from_terms(narrative.centroid_terms or [])


def _top_terms(
    narrative: Narrative,
    sources_by_id: dict[str, Source],
    df: dict[str, int],
    n_docs: int,
) -> list[str]:
    text_parts: list[str] = []
    for src_id in narrative.source_trail:
        s = sources_by_id.get(src_id)
        if s:
            text_parts.append(s.title)
            text_parts.append(s.body[:1200])
    tokens = tokenize(" ".join(text_parts))
    if not tokens:
        return list(narrative.centroid_terms)
    vec = _tf_idf_vector(tokens, df, n_docs)
    ranked = sorted(vec.items(), key=lambda kv: kv[1], reverse=True)
    return [t for t, _ in ranked[:TOP_TERMS_PER_CLUSTER]]


def _seed_narrative(nid: str, claim: Claim, sources_by_id: dict[str, Source]) -> Narrative:
    src = sources_by_id.get(claim.source_id)
    title = _derive_title(claim)
    subtitle = claim.thesis_summary or "Newly emerging narrative."
    first_seen = src.published_at if src else datetime.utcnow()
    n = Narrative(
        narrative_id=nid,
        title=title,
        subtitle=subtitle,
        stage=Stage.EMERGING,
        strength_score=0.0,
        first_seen=first_seen,
        last_updated=datetime.utcnow(),
        source_trail=[claim.source_id] if claim.source_id else [],
        claim_ids=[claim.claim_id],
        key_question="Will Tier 2 follow up on this thesis within 30 days?",
    )
    return n


def _derive_title(claim: Claim) -> str:
    base = claim.thesis_summary or claim.text or "New Narrative"
    base = base.split(".")[0].strip()
    return (base[:90] + "…") if len(base) > 90 else base


def _new_narrative_id(claim: Claim, suffix: int) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", claim.thesis_summary.lower()).strip("-")[:32] or "narrative"
    return f"nar_{base}_{suffix:02d}"
