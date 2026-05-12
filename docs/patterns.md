---
tags: [hogtron, agents, pattern]
aliases: [code-patterns, design-patterns]
---

# Patterns

The code-level patterns every department follows. If you're adding a new department or a new kind, follow these.

## The Brief / Asset / Finding pattern

Every department has typed inputs and outputs:

```python
class CreativeBrief(BaseModel):
    kind: BriefKind                    # discriminator — "shirt", "pdf_page", etc.
    payload: dict[str, Any]            # kind-specific inputs
    context: dict[str, Any] = {}       # API keys, cache dirs, optional flags
    requester: Optional[str] = None    # which pipeline called

class CreativeAsset(BaseModel):
    kind: BriefKind
    primary_url: Optional[str] = None  # e.g. Recraft CDN URL
    file_path: Optional[str] = None    # e.g. local cached PNG
    artifacts: dict[str, Any] = {}     # full intermediate data (art direction, etc.)
    metadata: dict[str, Any] = {}      # model used, timing, etc.
```

Research uses `ResearchBrief` / `ResearchFinding` with the same shape.

**Why**: a typed pydantic model gives validation at the boundary and a clear contract that callers can program against. The `payload` + `context` split keeps kind-specific inputs separate from cross-cutting config (keys, env, paths).

## The dispatcher pattern

```python
class Creative:
    def __init__(self, telemetry=None):
        self.telemetry = telemetry or NullSink()
        self._handlers: dict[BriefKind, Handler] = {
            "shirt": _design_shirt,
            "pdf_page": _design_pdf_page,
            "mockup": _design_mockup,
            "proposal_cover": _design_proposal_cover,
            "canva_asset": _design_canva_asset,
        }

    def design(self, brief: CreativeBrief) -> CreativeAsset:
        handler = self._handlers.get(brief.kind)
        if handler is None:
            raise ValueError(f"Creative has no handler for kind={brief.kind!r}")
        with working(self.telemetry, self.NAME, f"design({brief.kind})"):
            return handler(self, brief)
```

**Why**: adding a new kind is 2 lines (table entry + import) plus a new `_kind.py` file. Handlers can be swapped at runtime for testing (`register(kind, handler)`). The `working()` context wraps every call with telemetry — sets status to `working`, then `idle` (or `error`).

## The Provider Protocol pattern

Anything a department needs to *call out* to is injected, not imported:

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class TMProvider(Protocol):
    def query_exact(self, candidates: list[str]) -> list[dict]: ...
    def query_prefix_bucket(self, prefixes: set[str]) -> list[dict]: ...

class Research:
    def __init__(self, tm_provider: Optional[TMProvider] = None):
        self.tm_provider = tm_provider  # caller injects implementation
```

Caller writes the adapter:

```python
# FactoryHQ's SQLite-backed implementation
class FactorySQLiteTMProvider:
    def query_exact(self, candidates):
        with db.connect() as conn:
            ...

r = Research(tm_provider=FactorySQLiteTMProvider())
```

**Why**: the department doesn't know whether USPTO data lives in SQLite, Supabase, an in-memory dict, or a remote service. The migration from SQLite to Supabase is a one-line caller change with no department code touched.

Other places this pattern shows up:
- `TelemetrySink` Protocol in `_shared/telemetry.py` — caller supplies their log/status sink
- API keys throughout — keys come from `brief.context` first, env second, never hard-coded

## The cache_dir convention

Departments that produce files (Creative's shirt handler downloads Recraft PNGs, future PDF handler will write PDFs) accept an optional `cache_dir` in `brief.context`:

```python
cache_dir = brief.context.get("cache_dir") or DEFAULT_CACHE_DIR
# default: ~/.hogtron/<dept>_cache
```

Files written here are **ephemeral**. Anything that needs to persist (the Printify-uploaded image, the published Etsy listing URL) is handled by the caller after the department returns.

## The status convention for findings

Research's `ResearchFinding.status` semantics depend on kind:

- `ip_clear`: `"clear" | "blocked" | "tm_hit" | "error"`
- `geo_audit`, `seo_audit`: `"ok" | "error"`
- `platform_presence`: `"ok"` always (per-platform results in payload)
- `find_leads`, `cluster_concepts`, `trend_signals`: `"ok" | "error"`

**Why**: callers should be able to branch on `finding.status` without parsing payload. Reason strings in `finding.reason` are for humans; status is for code.

## The "skip what we don't need yet" rule

When porting a source module:
- Port the **core function** and the **stateless logic**
- Skip provider fallbacks the department doesn't need on day 1 (e.g. find_leads skipped Foursquare + Apify + email enrichment — the dashboard's tool still has them)
- Leave a comment in the port noting what was skipped so a future contributor knows
- Don't pre-build options. If something is needed later, add it then.

This keeps each port short and reviewable. The Creative shirt handler was 200 lines vs. the original `designer.py`'s 714 lines (the rest was Printify glue that stayed in Factory).
