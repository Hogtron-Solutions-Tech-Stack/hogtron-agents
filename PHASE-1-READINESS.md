# Phase 1 Readiness: `.parse()` Call Site Audit

**Status:** Audit complete. Phase 1 NOT approved — pending Sean's review of
2-week Phase 0 observation telemetry.

**Purpose:** When Sean approves Phase 1, this file tells the implementer
exactly what to expect at each call site. No surprises.

**Audited:** 2026-05-17 against `claude_router.py` and the reference
migration in `creative/_shirt.py`.

---

## Verdict

**9/9 sites: GO** — mechanically safe migrations. All follow the same
pattern as the reference `_shirt.py` migration:

- Single `.parse()` call (no loops, no chaining)
- Static Pydantic schema as `output_format=` (no dynamic schema construction)
- All on `claude-sonnet-4-6`
- Post-parse transformations only — no logic that depends on the SDK's
  internal `resp.usage` shape, no streaming, no tools

Estimated total work for Phase 1: **~12 lines of code change per file,
~2 hours including per-site smoke tests.**

---

## Per-file detail

| File | Schema | Notes |
|---|---|---|
| `marketing/_etsy_listing.py` | `_Listing` | Post-parse tag truncation + title clamp. Both work on the parsed object — survive the swap. |
| `marketing/_social_post.py` | `_PinCopy` | Cleanest of the bunch. Just reads `parsed_output` once. |
| `research/_cluster_concepts.py` | `_SynthesisOutput` | Wraps parse in `anthropic.APIError` catch. Router preserves that error class (we still import `anthropic` at the module top). |
| `marketing/_review_response.py` | `_ReviewReply` | Strips markdown `**`/`__`, enforces soft `word_limit` truncation. Post-parse only. |
| `marketing/social_media_manager/_caption.py` | `_CaptionSet` | Post-parse dedup loop over `hook_formulas`. Caller logic — orthogonal to swap. |
| `marketing/social_media_manager/_calendar.py` | `_Calendar` | Maps parsed slots to `SocialPost` list. No surprises. |
| `marketing/social_media_manager/_brand_review.py` | `_LLMReview` | Merges LLM score with deterministic checks (banned_hits, platform_fit). All downstream of `.parsed_output`. |
| `marketing/social_media_manager/_repurpose.py` | `_RepurposePlan` | Post-parse builds `SocialPost` list from `parsed.posts`. |
| `marketing/social_media_manager/_hashtags.py` | `_HashtagPack` | Tag-cleaning function called post-parse. Deterministic. |

---

## What we explicitly did NOT find

- **No dynamic schemas.** Every `output_format=` is a module-level class.
- **No multi-call patterns.** No site loops over `.parse()` or chains
  multiple calls in sequence.
- **No streaming.** All sites use the synchronous batch API.
- **No tool use mixed with parse.** None of these sites combine `tools=`
  with `output_format=`.
- **No reliance on `resp.usage` shape.** Sites only read `resp.parsed_output`.
- **No retry logic at the call-site level.** That lives in the router now.

---

## What needs to happen when Phase 1 is approved

For each file, replace:

```python
client = anthropic.Anthropic(api_key=key)
resp = client.messages.parse(
    model="claude-sonnet-4-6",
    max_tokens=...,
    system=...,
    messages=[...],
    output_format=Schema,
)
return resp.parsed_output
```

With:

```python
from .._shared.claude_router import route_messages_parse

resp = route_messages_parse(
    agent="<dept>.<kind>",          # e.g. "marketing.etsy_listing"
    model="claude-sonnet-4-6",
    max_tokens=...,
    system=...,
    messages=[...],
    output_format=Schema,
    api_key=key,
)
return resp.parsed_output
```

Delete the local `_client()` helper from each site. Drop the `import anthropic`
if nothing else in the file uses it.

### Verification per site

Re-use the pattern from `phase0_verify.py` but parameterized per site:

```powershell
$env:HOGTRON_FORCE_BACKEND = "api"
python -m hogtron_agents.<dept>.<module>  # with a test fixture
# Snapshot the parsed output

$env:HOGTRON_FORCE_BACKEND = $null
$env:HOGTRON_TRY_MAX = "true"
python -m hogtron_agents.<dept>.<module>
# Output should be semantically equivalent (not byte-equal — LLM output varies)
```

---

## Reference

- Router: `hogtron_agents/_shared/claude_router.py`
- Quota gate: `hogtron_agents/_shared/quota_gate.py`
- Reference migration: `hogtron_agents/creative/_shirt.py` (lines 183-218)
- Plan: `..\AGENT-AUTONOMY-PLAN.md` and `..\hogtron-cron-and-router-plan.md`
- Phase 0 verification harness: `phase0_verify.py`
- Phase 0 telemetry summary: `python -m hogtron_agents._shared.router_summary`
