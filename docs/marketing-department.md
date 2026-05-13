---
tags: [hogtron, agents, department, marketing]
aliases: [marketing, words-dept]
---

# Marketing Department

> Words that sell. Listing copy, social posts, blog content, review responses, ad copy, cold outreach.

Marketing produces **broadcast content** — words meant for many recipients through a channel. Compare with [[sales-department|Sales]], which produces closing motions for a specific prospect.

## Status

✅ Scaffolded. `etsy_listing` kind fully ported and smoke-tested.

| Kind | Status | Port source |
|---|---|---|
| `etsy_listing` | ✅ ported | FactoryHQ/agents/marketer.py write_listing() |
| `social_post` | ⏳ stub | FactoryHQ/agents/pinterester.py |
| `blog_post` | ⏳ stub | hogtron-dashboard Social-to-Blog Engine |
| `review_response` | ⏳ stub | hogtron-dashboard AI Smart Review Responder |
| `ad_copy` | ⏳ stub (net-new) | — |
| `email_outreach` | ⏳ stub (net-new) | — |

## Usage

```python
from hogtron_agents.marketing import Marketing, MarketingBrief

m = Marketing()
asset = m.write(MarketingBrief(
    kind="etsy_listing",
    payload={
        "phrase": "World's Okayest Grill Dad",
        "concept": "father's day humor",
        "audience": "casual grilling dads, gift buyers",
        "saturation": "medium",
    },
    context={
        # optional, falls back to env ANTHROPIC_API_KEY
        "anthropic_api_key": "...",
        "model": "claude-opus-4-7",  # or claude-haiku-4-5 for cheaper
    },
))

# asset.primary_text                  -> the Etsy title
# asset.payload["title"]              -> same, ≤140 chars guaranteed
# asset.payload["description"]        -> ≥200 chars, with hook + bullets
# asset.payload["tags"]               -> list of 8-13, each ≤20 chars, lowercase
# asset.payload["seo_rationale"]      -> one sentence explaining keyword choices
```

## The etsy_listing handler in detail

The Pydantic `_Listing` schema enforces:
- Title ≤140 chars (Etsy limit)
- Description ≥200 chars (minimum to be search-relevant)
- 8-13 tags (Etsy max is 13; below 8 is leaving SEO on the table)

The SYSTEM_PROMPT bakes in Etsy algorithm awareness:
- Title keywords carry most weight; first 40 chars highest weight
- Tags should be **phrases**, not single words
- Tag-title overlap helps; don't waste tags on duplicates
- Buyers search problem-state language ("tired mom shirt") not formal language

After Claude returns, final guardrails kick in:
- Each tag trimmed + lowercased + truncated to 20 chars (Etsy silently drops longer)
- Title truncated to 140 chars
- Tag list capped at 13

## What's NOT here (and why)

- **Pushing the copy to Printify** — that's [[operations-department|Operations]] (`publish_etsy` kind). Marketing produces *words*; Operations *moves them to external systems*.
- **DB row updates** — caller-owned. FactoryHQ's marketer.py wraps the `Marketing.write()` call with the SQL query for `status='approved'` designs and the post-call status flip to `listing_ready`.
- **A/B variant generation** — `MarketingAsset.variants` is reserved for this, but `etsy_listing` returns one variant. Add multi-variant on the next session if/when we want to A/B test.

## Migration to existing callers

**Shipped** (commit `4029c56` on FactoryHQ). `agents/marketer.py` shrank from 263 → 203 lines. `write_listing()` is now a queue runner: fetches approved designs from DB, builds a `MarketingBrief(kind='etsy_listing', ...)` per row, delegates to `Marketing.write()`, pushes the returned title/description/tags to Printify, flips DB status to `listing_ready`. The `_Listing` schema, Etsy SYSTEM_PROMPT, and final guardrails (tag truncation, title length cap) all live in `_etsy_listing.py` now.

`publish()` (Phase 2 — push Printify draft to Etsy) is unchanged. Will migrate to `Operations(publish_etsy)` when that handler ships.

## Adding a new kind

Same pattern as [[creative-department|Creative]]: write `_kind.py` with `kind_name(brief) -> MarketingAsset`, add to dispatcher in `marketing.py`. See [[patterns]].
