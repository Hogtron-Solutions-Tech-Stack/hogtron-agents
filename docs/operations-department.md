---
tags: [hogtron, agents, department, operations]
aliases: [operations, ops-dept, publishing]
---

# Operations Department

> Shipping things. Publishing, deploys, scheduled jobs, infra health, channel management.

Operations *moves artifacts from internal state to external systems*. Every kind here hits an external API (Printify, Etsy, Shopify, Pinterest, Railway, ffmpeg). The keystone difference from other departments: every action has real-world consequences.

## Status

✅ Scaffolded. `printify_upload` kind fully ported and smoke-tested. Live test deferred (would create a real Printify draft product).

| Kind | Status | Port source |
|---|---|---|
| `printify_upload` | ✅ ported | FactoryHQ/agents/designer.py upload() (Phase 3) |
| `publish_etsy` | ⏳ stub | FactoryHQ/agents/marketer.py publish() |
| `publish_shopify` | ⏳ stub (net-new) | — |
| `publish_pinterest` | ⏳ stub | FactoryHQ/agents/pinterester.py |
| `render_video` | ⏳ stub | FactoryHQ/agents/distributor.py + tools/video.py |
| `deploy_mockup` | ⏳ stub | hogtron-dashboard mockup deploy |
| `deploy_proposal` | ⏳ stub | hogtron-dashboard proposal share |

## Usage

```python
from hogtron_agents.operations import Operations, OperationsBrief

o = Operations()
result = o.do(OperationsBrief(
    kind="printify_upload",
    payload={
        "art_local_path": "/path/to/design.png",
        "file_name": "design_42.png",
        "shop_id": "27497214",
        "title": "World's Okayest Grill Dad Shirt | Funny Father's Day Gift",
        "description": "...",
        "tags": ["grill dad shirt", "fathers day", ...],
        "placement_y": 0.38,                    # optional, from Creative ArtDirection
        "variant_ids": [12100, 12101, 12102],   # required: sizes/colors to enable
        # optional:
        # "blueprint_id": 384,                  # Bella+Canvas 3001
        # "print_provider_id": 29,              # Monster Digital
    },
    context={"printify_api_key": "..."},  # optional, falls back to env
))

# result.success            -> bool
# result.external_id        -> Printify product_id
# result.external_url       -> primary mockup URL
# result.payload["image_id"] -> Printify image_id (for later swaps via regenerate)
# result.cost_estimate_usd  -> 0.0 (drafts are free; cost lands on Etsy publish)
# result.error              -> str | None
```

## The autonomy ladder applies here

Every Operations kind is a candidate for the [[architecture#the-autonomy-ladder|autonomy ladder]]. At rung 0 (today), each call is gated by a human; at rung 2, low-cost actions auto-fire and high-cost actions queue.

Rung-2 examples:
- `printify_upload` (free, easily reversible) → auto-allow for high-confidence Creative assets
- `publish_etsy` ($0.20 + 6.5% commission, recoverable but visible) → auto-allow once daily volume cap is set
- `publish_pinterest` (free, soft consequences) → auto-allow with rate limit
- `render_video` (local compute, no spend) → always auto

Rung-4+ examples:
- Direct client comms via Operations (e.g. sending the proposal email) → never auto without budget caps + per-message review queue

The `cost_estimate_usd` field on `OperationsResult` is what Layer 3 will use to enforce daily budget caps.

## Why Printify HTTP is inlined here (not imported from FactoryHQ)

The Operations dept is meant to be self-contained — FactoryHQ depends on `hogtron-agents`, not the other way around. So the small Printify upload + create_product calls were inlined into `_printify_upload.py` rather than importing from `FactoryHQ/tools/printify.py`. FactoryHQ's `tools/printify.py` is still in active use by `designer.py` (for `regenerate`) and `marketer.py` (for `publish`). Both will eventually call Operations instead, at which point `tools/printify.py` can be deleted.

## Migration to existing callers

**Pending.** FactoryHQ's `designer.py::upload()` (Phase 3 of the queue runner) is unchanged. Migration plan: replace the inline Printify calls in `_upload_inner()` with `Operations().do(OperationsBrief(kind='printify_upload', ...))`, keep the DB row updates in designer.py. Same shape as the [[creative-department|Creative]] migration.

## Adding a new kind

Same pattern as the other departments — write `_kind.py` with the external API call(s), add to dispatcher. **Specific to Operations**: always set `cost_estimate_usd` accurately so budget caps work. Always wrap external calls in try/except and return `OperationsResult(success=False, error=...)` rather than propagating the exception — callers need to make policy decisions on failures, not catch arbitrary library errors.
