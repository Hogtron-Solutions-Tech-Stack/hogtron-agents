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

### Layer 2 — Department agent loops (Claude tool-use)
**Optional reasoning layer over Layer 1. Pilot shipped on Research (2026-05-12).**

When a caller wants Claude to *decide* which Layer 1 calls to make, they hit Layer 2:

```python
r = Research(tm_provider=...)
result = r.run_autonomous(
    "List 3 IP-clear shirt phrases for graduation gifts.",
    anthropic_api_key=...,
)
print(result.summary)        # the model's natural-language wrap-up
print(result.tool_calls)     # what got chained
print(result.cost_usd)       # estimated spend on Claude tokens
```

Internally the loop has Layer 1 kinds exposed as Claude tools (`tool_use` API). The model reasons, picks the right kinds in the right order, observes results, adapts. Returns an `AutonomousResult` with the full tool-call log, all underlying `ResearchFindings`, cost, and iteration count.

**Implementation choice — thin loop over the anthropic SDK, not the `claude-agent-sdk` package.** ~80 lines in [`_shared/agent_loop.py`](C:/Users/sbilg/Code/hogtron-agents/hogtron_agents/_shared/agent_loop.py). No new deps, transparent control flow, easy to inject telemetry + cost tracking. Swap in the SDK later if we want its features.

**First live result (2026-05-12, Research pilot):**
- Directive: `"List 3 IP-clear shirt phrases for graduation gifts."`
- Agent chained: `trend_signals` (1 query) → `cluster_concepts` (synth 3 concepts) → `ip_clear` ×5 (vetted candidates one by one)
- Caught a real TM hit on `"Class of 2025: Now With Extra Letters After My Name"` (live apparel-class mark `CLASS OF 2020`, serial 88878430), substituted a Masters Degree phrase, returned 3 cleared
- **Bonus: surfaced a meta-insight** — `"Class of [year]"` phrasings are risky. A deterministic pipeline doesn't notice that pattern; the agent does. This is the Layer 2 dividend.
- 5 iterations, 7 tool calls, 60 sec, $0.55

Next: pilot Layer 2 on Marketing, Sales, Operations, Creative. Same shape — each gets a `run_autonomous(directive)` method, hand-tuned system prompt + tool JSON schemas.

### Layer 3 — CEO loop (cross-department orchestration)
**Shipped 2026-05-12 (commit `0a2e5b7`).**

One outer Claude tool-use loop with Sean + Anthony's voice in the system prompt. Tools are the 5 departments' `run_autonomous()` methods. Each CEO tool call is itself a Layer 2 agent loop, so costs and iterations compound.

```python
from hogtron_agents.ceo import CEO
from hogtron_agents.research import Research
# ... etc

ceo = CEO(
    research=Research(tm_provider=...),
    creative=Creative(),
    marketing=Marketing(),
    sales=Sales(),
    operations=Operations(),
)

result = ceo.run_autonomous(
    "Find an IP-clear Father's Day grilling shirt phrase, design it, "
    "write Etsy + Pinterest copy. Hold publishing.",
    anthropic_api_key=...,
)
print(result.summary)         # journal-ready
print(result.dept_calls)      # per-dept breakdown with iter/cost
print(result.cost_usd)        # CEO + all nested dept Claude tokens
print(result.ops_cost_usd)    # real-world spend (Etsy fees, etc.)
```

**SYSTEM_PROMPT** holds Sean + Anthony's voice + company context: 2 product lines (Factory + Agency), 5 departments with one-line responsibilities, autonomy-ladder rung 0 enforcement (HOLD publish_* without explicit auth), and the journal output format (**What I did** / **What you'll find** / **Open items** / **Total cost**).

**First live result (2026-05-12):**
- Directive: "Find ONE IP-clear shirt phrase for Father day grilling. Have Creative design the shirt. Have Marketing write both Etsy listing + Pinterest copy. HOLD all publishing. Keep Research efficient: 1 trend query is enough."
- CEO 4 iter, 161s, $1.08 total Claude (Research $0.39 + Creative $0.11 + Marketing $0.23 + CEO orchestration $0.35)
- Outcome: "Smoke Ring Enthusiast" cleared + designed + listing/pin copy written, publishing held per autonomy ladder
- **The Layer 3 dividend**: the CEO autonomously surfaced 2 real downstream issues — Recraft output is 2048² but Printify wants 4500×5400 (needs upscale), and the listing description names a Bella+Canvas blank that needs verification. Exactly the kind of follow-up signals a journal entry needs without being asked.

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
