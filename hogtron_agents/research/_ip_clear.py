"""IP-clearance handler — blocklist + USPTO trademark check.

Two-stage check for a candidate phrase:
  1. Blocklist (pure, no IO) — catches named characters, brands, public
     figures, lyric fragments. Fast hard reject.
  2. USPTO trademark match — exact + n-gram + fuzzy against live marks
     in apparel-relevant classes (025, 035).

The TM data lookup is delegated to a TMProvider (Protocol) injected at
Research-construction time. Logic lives here; storage is the caller's
problem. This is what lets FactoryHQ keep its SQLite tm_marks today and
migrate to Supabase later without touching this code.
"""
from __future__ import annotations

import re
from typing import Protocol, Optional, runtime_checkable

from rapidfuzz import fuzz

from .briefs import ResearchBrief, ResearchFinding
from . import _blocklist_data as data


APPAREL_CLASSES = ("025", "035")


# --- TMProvider Protocol ------------------------------------------------

@runtime_checkable
class TMProvider(Protocol):
    """Caller-supplied access to the local USPTO trademark index.

    FactoryHQ's implementation queries its SQLite `tm_marks` table.
    A future Supabase-backed implementation will query Postgres. The
    Research department doesn't care which.
    """

    def query_exact(self, normalized_candidates: list[str]) -> list[dict]:
        """Return live apparel-class marks whose `mark_normalized` equals
        any candidate. Each mark dict should include at least:
            serial_number, mark_text, mark_normalized,
            international_classes, live_dead, status_code
        """
        ...

    def query_prefix_bucket(self, prefixes: set[str]) -> list[dict]:
        """Return live apparel-class marks whose `mark_normalized` starts
        with any 3-char prefix. Caller will rapidfuzz-score them."""
        ...


# --- Pure helpers -------------------------------------------------------

def _normalize(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _ngrams(words: list[str], lo: int, hi: int) -> list[str]:
    out = []
    for n in range(lo, hi + 1):
        for i in range(len(words) - n + 1):
            slice_words = words[i:i + n]
            phrase = " ".join(slice_words)
            if len(phrase) < data.NGRAM_MIN_CHARS:
                continue
            if all(w in data.STOPWORDS for w in slice_words):
                continue
            out.append(phrase)
    return out


def _blocklist_check(phrase: str) -> Optional[dict]:
    """Return blocklist match info if hit, else None."""
    p = phrase.lower()
    hits = []
    for term in data.CHARACTERS_BRANDS:
        if re.search(rf"\b{re.escape(term)}\b", p):
            hits.append(("character_or_brand", term))
    for term in data.PUBLIC_FIGURES:
        if re.search(rf"\b{re.escape(term)}\b", p):
            hits.append(("public_figure", term))
    for term in data.LYRIC_FRAGMENTS:
        if term in p:
            hits.append(("possible_lyric", term))
    if not hits:
        return None
    cats = sorted({c for c, _ in hits})
    return {
        "reason": f"blocklist hit: {', '.join(cats)}",
        "matches": [t for _, t in hits],
        "categories": cats,
    }


# --- Public handler -----------------------------------------------------

def ip_clear(
    brief: ResearchBrief,
    tm_provider: Optional[TMProvider] = None,
) -> ResearchFinding:
    """Clear a candidate phrase for use on shirt designs, logos, etc.

    brief.payload:
      phrase (required) — the candidate text

    Returns ResearchFinding with status in {"clear", "blocked", "tm_hit", "error"}.
    """
    phrase = brief.payload.get("phrase")
    if not phrase:
        raise ValueError("ip_clear brief.payload must include 'phrase'")

    # Stage 1 — blocklist
    block = _blocklist_check(phrase)
    if block:
        return ResearchFinding(
            kind="ip_clear",
            status="blocked",
            payload={"matches": block["matches"], "categories": block["categories"]},
            reason=block["reason"],
        )

    # Stage 2 — USPTO TM
    if tm_provider is None:
        return ResearchFinding(
            kind="ip_clear",
            status="error",
            reason="no TMProvider configured; blocklist passed but TM check skipped",
            payload={"blocklist": "clear"},
        )

    norm = _normalize(phrase)
    if not norm:
        return ResearchFinding(
            kind="ip_clear",
            status="clear",
            reason="empty phrase after normalization",
        )

    words = norm.split()
    ngrams = _ngrams(words, data.NGRAM_MIN_WORDS, data.NGRAM_MAX_WORDS)
    candidates = list({norm, *ngrams})

    exact_hits = tm_provider.query_exact(candidates)

    prefixes = {n[:3] for n in ngrams if len(n) >= 3}
    bucket = tm_provider.query_prefix_bucket(prefixes) if prefixes else []
    fuzzy_hits = []
    for c in bucket:
        mark_norm = c.get("mark_normalized") or ""
        best = max((fuzz.ratio(mark_norm, ng) for ng in ngrams), default=0)
        if best >= data.FUZZY_THRESHOLD and mark_norm not in ngrams:
            c = dict(c, _fuzzy_score=best)
            fuzzy_hits.append(c)

    seen = {h["serial_number"] for h in exact_hits}
    for h in fuzzy_hits:
        if h["serial_number"] not in seen:
            exact_hits.append(h)
            seen.add(h["serial_number"])

    if exact_hits:
        return ResearchFinding(
            kind="ip_clear",
            status="tm_hit",
            payload={"marks": exact_hits},
            metadata={"n_candidates": len(candidates), "n_ngrams": len(ngrams)},
            reason=f"{len(exact_hits)} live apparel-class mark(s) match",
        )
    return ResearchFinding(
        kind="ip_clear",
        status="clear",
        metadata={"n_candidates": len(candidates), "n_ngrams": len(ngrams)},
        reason=f"no apparel-class match across {len(candidates)} candidates",
    )
