---
tags: [hogtron, agents, architecture, decision]
aliases: [layers, three-layer-model]
---

# Architecture

## The 3-layer model

```
┌─────────────────────────────────────────────────────────┐
│  LAYER 3 — CEO Loop                                     │
│  Reads company state, dispatches across departments,    │
│  reports to Journal. Sean+Anthony's voice in the prompt │
│  (not built yet — waits for all 5 departments at L1)    │
└────────────────────────┬────────────────────────────────┘
                         │ directives
       ┌─────────────────┼─────────────────┐
       ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ LAYER 2      │  │ LAYER 2      │  │ LAYER 2      │
│ Creative     │  │ Research     │  │ Marketing…   │
│ Agent Loop   │  │ Agent Loop   │  │              │
│ (Claude SDK) │  │ (Claude SDK) │  │              │
│ (not built)  │  │ (not built)  │  │              │
└──────┬───────┘  └──────┬───────┘  └──────────────┘
       │ tool calls      │ tool calls
       ▼                 ▼
┌──────────────┐  ┌──────────────┐
│ LAYER 1      │  │ LAYER 1      │
│ Creative     │  │ Research     │
│ Department   │  │ Department   │
│ ✅ built     │  │ ✅ built     │
│ design(brief)│  │ do(brief)    │
└──────────────┘  └──────────────┘
       ▲                 ▲
       │ called by       │ called by
┌──────┴─────────────────┴──────────────────────────────┐
│  Existing pipelines (call Layer 1 directly today)     │
│  FactoryHQ schedulers · hogtron-dashboard routes      │
└───────────────────────────────────────────────────────┘
```

### Layer 1 — Department classes (Python)
**Deterministic. What we built first.**

Each department is a Python class with a single entrypoint that dispatches by `kind`:

```python
Creative().design(CreativeBrief(kind="shirt", payload={...}))
Research().do(ResearchBrief(kind="ip_clear", payload={...}))
```

No LLM reasoning at this layer. Each kind is a stateless function. Callers own DB / state machines / caching. See [[patterns]] for the details.

Callable today from:
- FactoryHQ schedulers (APScheduler cron jobs)
- hogtron-dashboard route handlers
- Anywhere Python runs and `hogtron-agents` is installed

### Layer 2 — Department agent loops (Claude Agent SDK)
**Optional reasoning layer over Layer 1.**

When a caller wants Claude to *decide* which Layer 1 calls to make, they hit Layer 2:

```python
Research.run_autonomous(
  "Find me 20 high-saturation phrases for Father's Day shirts"
)
```

Internally the agent loop has Layer 1 methods exposed as tools (via the Claude Agent SDK). It reasons, picks `trend_signals` → `cluster_concepts` → `ip_clear`, handles its own retries, and returns the consolidated findings.

Not built yet. Will probably pilot on **Research** first — cheapest mistakes (a bad scrape costs cents; a bad design costs an Etsy strike).

### Layer 3 — CEO loop (cross-department orchestration)
**The "fully autonomous" piece.**

One outer Claude Agent loop with Sean + Anthony's voice in the system prompt. Holds company goals, the calendar, a budget, the Journal. Dispatches directives across departments:

```
CEO loop wakes up daily ➜
  read company state (live listings, pipeline, revenue, holidays approaching)
  decide priorities for the day
  fire Research.run_autonomous(...) + Marketing.run_autonomous(...) in parallel
  consolidate findings + write a Journal entry
```

Built last. Requires all 5 departments at Layer 1, ideally 2+ at Layer 2.

---

## The autonomy ladder

We get to "fully autonomous" by walking rungs, not jumping. Each rung is a **policy change** (what risk threshold auto-passes), not a code rewrite. The Layer 1/2/3 architecture supports any rung.

| Rung | What's automated | Human still gates |
|---|---|---|
| **0 (today)** | Scheduled scrapes + synthesis | Concept approval, mockup approval, sending anything external |
| **1** | + Concept auto-approve (low-risk phrases skip the human queue) | Mockup approval, external sends |
| **2** | + Mockup auto-publish for high-confidence designs | External sends, refunds, large spend |
| **3** | + Lead outreach drafts queue for click-to-send | Direct sending, payments |
| **4** | + Auto-send to low-stakes channels (Pinterest cross-posts, blog drafts) | Direct client comms, large spend |
| **5 (eventual)** | + Direct client comms with budget caps ($X/day, Y messages) | Strategy pivots, hires, contracts |

We're on **rung 0** today. The Creative + Research builds set the foundation; we don't move rungs until all 5 departments exist and we have decent observability.

---

## Design principles (decisions worth preserving)

### Stateless departments, stateful callers
Departments don't write to databases. They take a brief, return a finding. Callers own the DB row, the status state machine, the cache. Why: lets the same department serve Factory (SQLite today, [[infra|Supabase tomorrow]]) and Agency (Supabase) and any future caller without rewriting the department.

### Inject dependencies via Protocols, not config
Anything a department needs to *call out* to (a TM database, a Claude client, an image API) gets passed in. We use `typing.Protocol` so callers can supply any object that matches the shape. Example: `TMProvider` Protocol in [[research-department]] — FactoryHQ implements it with SQLite, future code implements it with Supabase, the department doesn't care.

### One file per kind
Each `kind` in a department's dispatch table lives in its own `_kind.py` module. Adding a kind is a 2-line change to the dispatch table + a new file. Removing a kind is the reverse. No mega-files.

### IP guardrails are infrastructure
Brand / character / trademark checks aren't pipeline-specific — they're company infrastructure. They live in the Research department's `ip_clear` kind and are called from every pipeline that touches Etsy. One source of truth.

### Don't migrate working callers until the new module is proven
When we port `designer.py` from Factory into Creative, we don't immediately rewrite Factory. We add the new module, smoke-test it, optionally live-test, then change the caller in a separate step. Lets us back out cheaply if the abstraction was wrong.

See [[patterns]] for the code-level patterns these principles translate into.
