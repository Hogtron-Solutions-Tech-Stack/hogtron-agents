---
tags: [hogtron, agents, department, creative]
aliases: [creative, design-dept]
---

# Creative Department

> Visual production: shirts, PDFs, mockups, proposals, Canva assets, future client storefront themes.

## Status

✅ Live. `shirt` kind fully ported and live-tested (Claude + Recraft, 25s end-to-end, IP guardrail clean).

| Kind | Status | Port source |
|---|---|---|
| `shirt` | ✅ live | FactoryHQ/agents/designer.py (phases 1-2) |
| `pdf_page` | ⏳ stub | FactoryHQ/agents/pdf_designer.py |
| `mockup` | ⏳ stub | hogtron-dashboard mockup generation + Theme Studio |
| `proposal_cover` | ⏳ stub | hogtron-dashboard proposal generator |
| `canva_asset` | ⏳ stub | hogtron-canva skill + Canva MCP |

## Usage

```python
from hogtron_agents.creative import Creative, CreativeBrief

c = Creative()
asset = c.design(CreativeBrief(
    kind="shirt",
    payload={
        "phrase": "World's Okayest Grill Dad",
        "audience": "Father's Day gift for casual grilling dads",
        "saturation": "medium",
    },
    context={
        # all optional — fall back to env vars
        "anthropic_api_key": "...",
        "recraft_api_key": "...",
        "cache_dir": "/some/path",
        "design_id": "any-unique-id",
    },
))

# asset.primary_url       — Recraft CDN URL
# asset.file_path         — local cached PNG
# asset.artifacts["art_direction"]  — full ArtDirection dict
# asset.artifacts["recraft_prompt"] — prompt that generated the image
```

## What's NOT here (and why)

- **Printify upload + product creation** — that's Operations (publishing/distribution). Lives in `FactoryHQ/agents/designer.py` as the `upload()` phase, will eventually move to the Operations department.
- **Etsy listing copy + tags** — that's Marketing. Lives in `FactoryHQ/agents/marketer.py`.
- **Supabase Storage upload of the PNG** — that's caller-owned (FactoryHQ's designer.py does it after Creative returns the local file).
- **HogTron-branded merch print prep** — `prep_hogtron_assets()` is pure PIL recoloring, unrelated to POD art generation. Stays in FactoryHQ for now.

## The shirt handler in detail

Two stateless phases that run as one call:

1. **Art direction** — Claude Opus 4.7 with adaptive thinking reads the phrase + audience and produces a structured `ArtDirection` (shirt color, typography style, layout, accent element, color palette, mood tags, recraft prompt, placement_y).
2. **Image generation** — Recraft renders a transparent PNG from the art prompt. Image is downloaded to a local cache dir.

### IP guardrails (the SYSTEM_PROMPT)

The Creative department enforces IP rules at prompt-time. Even though phrases arrive *already cleared* by [[research-department|Research]]'s `ip_clear`, the art around the phrase could reintroduce risk if Claude generated a Pikachu accent on a coffee shirt.

The system prompt locks down:
- No named characters, mascots, brand logos, athletes, celebrities, song lyrics, movie/TV imagery, sports teams, college logos
- Generic motifs only (sun, moon, stars, coffee cup, flowers, leaves, arrows, hearts, geometric shapes, abstract patterns)
- The recraft_prompt MUST NOT mention garment words (shirt, t-shirt, tee, garment, neckline, collar, sleeve) — that causes Recraft to draw a shirt-on-shirt, ruining the listing

See [[research-department#ip_clear]] for the phrase-side guard; together they form the [[architecture#design-principles|IP guardrails as infrastructure]].

## Migration impact on FactoryHQ

`FactoryHQ/agents/designer.py` shrank from **714 lines → 416 lines** (cleared the Claude prompt + ArtDirection schema + Recraft client + IP rules — all now in Creative). The file kept its queue-runner role (DB loop, Printify upload, status state machine).

The auto-chain on brief approval (`app.py`) went from 3 calls (`art_direct + generate + upload`) to 2 (`design + upload`). Status flow `pending_art → art_ready → mockup_ready` became `pending_design → art_ready → mockup_ready` since the two phases run as one transaction.

## Live test results (2026-05-12)

```
phrase: "World's Okayest Grill Dad"
end-to-end: 25.4s
file_path: design_pilot_1778626908.png (1.88 MB)
art direction:
  shirt_color:     heather grey
  typography:      bold condensed sans-serif with slab accents
  layout:          three stacked lines, OKAYEST as hero
  accent:          crossed grilling spatula and tongs with smoke curls
  palette:         #1A1A1A, #C0392B, #E8B04B
  mood:            bold, retro, humorous, masculine, vintage
  placement_y:     0.38
IP guardrail (forbidden garment words in recraft_prompt): CLEAN
```

## Adding a new kind

1. Decide the brief shape — what does `payload` need?
2. Write `_kind.py` with a single `design_kind(brief) -> CreativeAsset` function. Keep it stateless.
3. Add the import in `creative/creative.py`'s `_handlers` dict.
4. Wire dispatch — replace the `NotImplementedError` stub.
5. Smoke-test (import + minimal validation).
6. Live-test against a real input if the dependencies are cheap.
7. Commit as one focused change.

See [[patterns]] for the shape every kind should follow.
