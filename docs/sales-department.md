---
tags: [hogtron, agents, department, sales]
aliases: [sales, closing-dept]
---

# Sales Department

> Closing motions for a specific prospect. Proposals, audit reports, follow-ups, quotes, contracts.

Sales is **specific-recipient content** with intent to convert. Compare with [[marketing-department|Marketing]], which is broadcast content for many recipients.

## Status

✅ Scaffolded. `aggregator_audit_report` kind fully ported and smoke-tested with parity check against the dashboard's existing generator.

| Kind | Status | Port source |
|---|---|---|
| `aggregator_audit_report` | ✅ ported | hogtron-dashboard/tools/aggregator_audit/generator.py |
| `proposal` | ⏳ stub | hogtron-dashboard proposals + reference_proposal_template.md |
| `follow_up` | ⏳ stub (net-new) | — |
| `pricing_quote` | ⏳ stub (net-new, pulls from reference_pricing.md) | — |
| `contract` | ⏳ stub (net-new) | — |

## Usage

```python
from hogtron_agents.sales import Sales, SalesBrief

s = Sales()
asset = s.build(SalesBrief(
    kind="aggregator_audit_report",
    payload={
        "restaurant": {
            "name": "Tony's Pizza", "address": "123 Main St",
            "city": "Bethlehem", "state": "PA", "zip": "18015",
            "phone": "(610) 555-0123", "website": "tonyspizza.com",
            "cuisine": "pizzeria",
        },
        "platform_status": {
            "doordash": {"listed": True, "rating": 4.5, "review_count": 200},
            "ubereats": {"listed": False},
            "grubhub": {"listed": True, "rating": 4.0, "review_count": 75},
            "slice": {"listed": False},
        },
        # optional override fields:
        # competitor_count, hogtron_setup_fee, prepared_by, prepared_for_meeting_date, ...
    },
))

# asset.summary                              -> one-line description
# asset.payload                              -> full report dict for the Jinja template
# asset.metadata["projection_mid_monthly"]   -> $4,620 (in test case above)
```

## The aggregator_audit_report handler in detail

Pure business logic — **no LLM, no IO**. Given a restaurant + per-platform presence (typically sourced from [[research-department#platform_presence|Research.platform_presence]]), produces:

- **Per-platform analysis**: status (listed/missing/unknown), color, blurb, merchant signup link. Rating <4.3 flags the listing for optimization.
- **Revenue projection** at low/mid/high tiers with diminishing returns: `lift × [1.0, 0.85, 0.65, 0.45]` per additional platform + 25% bump per optimized listing.
- **Competitive intel**: how you compare against the median competitor's platform count in your market.
- **Ranked HogTron service recommendations**: each missing platform gets a "Join X" rec with setup fee; underperforming listings get an "Optimize X" rec with monthly fee; fully-optimized restaurants get a "Maintain" rec.

The `PLATFORM_META` dict (DoorDash, Uber Eats, Grubhub, Slice — with colors, blurbs, signup URLs) and revenue-lift constants live in the handler, not in payload — these are HogTron-specific config, not per-call inputs.

## Composition with other departments

Sales is where **multi-department outputs come together**. A full proposal flow looks like:

```
1. Research.do(find_leads)         -> candidate businesses
2. Research.do(seo_audit)          -> SEO score for the lead
3. Research.do(geo_audit)          -> GEO score for the lead
4. Research.do(platform_presence)  -> which aggregators (if restaurant)
5. Creative.design(mockup)         -> client website mockup (when ported)
6. Marketing.write(email_outreach) -> cold outreach copy (when ported)
7. Sales.build(proposal)           -> assemble all of the above into the deliverable
8. Sales.build(pricing_quote)      -> tiered pricing
9. Operations.do(deploy_proposal)  -> publish to share URL (when ported)
```

Each step is a department call. Sales doesn't *do* the upstream work — it composes findings/assets that other departments produced.

## Migration to existing callers

**Pending.** The dashboard's `tools/aggregator_audit/generator.py::generate_audit()` is unchanged. Migration plan: have the route handler at `routes/aggregator_audit.py` call `Sales().build(SalesBrief(kind='aggregator_audit_report', ...))` instead, unwrap `asset.payload`, render to the existing Jinja template. The dashboard's `generator.py` becomes a thin re-export (or gets deleted) once parity is proven.

## Adding a new kind

Same pattern as [[creative-department|Creative]]. See [[patterns]].
