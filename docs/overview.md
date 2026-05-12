---
tags: [hogtron, agents, overview]
aliases: [intro, what-is-this]
---

# Overview — The HogTron Agentic System

*For Anthony, or anyone reading this cold.*

## The problem we're solving

We have two AI-heavy systems that grew up independently:

- **FactoryHQ** — the print-on-demand shirt business. A pipeline of agents (Researcher, Designer, Marketer, Distributor) that scrape trends, design shirts, list them on Etsy, render social videos. Plus a parallel PDF production line (Outliner, Writer, Designer, Critic, Marketer) for PDF products. **13 agent files. 3,308 lines.**
- **hogtron-dashboard** — the freelance agency control panel. Lead scraping, SEO/GEO audits, restaurant aggregator audits, client proposals, mockup gallery deploys. A different set of tools doing similar things.

Both systems do **research** (find businesses, find trends, check trademarks, audit competitors). Both do **creative work** (design shirts, design PDFs, build client mockups, make proposal covers). Both do **marketing** (Etsy listings, social posts, blog content, review responses). They duplicate each other and they don't share code.

When Sean adds a new product line, he ends up rewriting the same agents again.

## The fix

Five **department heads**, each a Python class in a shared package. Any product line — Factory, Agency, PDF line, future Shopify storefront, whatever — calls into the same five departments.

| Department | What it does | Status |
|---|---|---|
| [[creative-department\|Creative]] | Visual production: shirts, mockups, proposals, PDFs, Canva | ✅ live (shirt kind) |
| [[research-department\|Research]] | Intel: trends, leads, IP clearance, audits, platform detection | ✅ live (all 7 kinds) |
| Marketing | Words that sell: listings, social copy, ads, reviews, blogs | ⏳ planned |
| Sales | Closing motions: proposals, follow-ups, pricing, contracts | ⏳ planned |
| Operations | Shipping things: publishing, deploys, scheduled jobs | ⏳ planned |

Sean and Anthony sit above as **CEOs** — strategic direction, approvals, calendar, customer relationships.

## The 3-layer model in one paragraph

**Layer 1** is what we just built — department classes you call programmatically: `Creative().design(brief)`. No LLM reasoning at this layer; just deterministic dispatchers that hide the underlying tools. **Layer 2** is autonomous reasoning *within* a department: `Creative.run_autonomous("design 5 shirts for Father's Day")` — uses the Claude Agent SDK to chain Layer 1 calls. **Layer 3** is the CEO loop — cross-department orchestration that reads company state and dispatches directives. Built last, on top of the other two.

See [[architecture]] for the full diagram and the **autonomy ladder** that takes us from scheduled cron jobs (today) to a fully autonomous company (eventual).

## Why this matters

- **Less duplication.** Add a product line, plug into the same 5 departments.
- **Better IP guardrails.** The trademark/blocklist code lives in one place (Research), not copy-pasted into every pipeline.
- **Cheaper to evolve.** Want to swap our image generator from Recraft to something else? One change in one place, every product line benefits.
- **Path to autonomy.** Without this consolidation, "fully autonomous" means orchestrating 13 different scripts. With it, it's 5 well-defined interfaces.
- **Both partners can extend it.** Same API regardless of which product line you're working on. Less context-switching, less duplicated work between Sean and Anthony.

## How to read code in this repo

```
hogtron-agents/
├── pyproject.toml          # pip install -e . to use it locally
├── hogtron_agents/
│   ├── _shared/            # brand constants, telemetry, recraft client
│   ├── creative/           # the Creative department
│   │   ├── briefs.py       # CreativeBrief, CreativeAsset types
│   │   ├── creative.py     # the Creative class + dispatch table
│   │   └── _shirt.py       # one kind's logic
│   └── research/           # the Research department
│       ├── briefs.py       # ResearchBrief, ResearchFinding types
│       ├── research.py     # the Research class + dispatch table
│       ├── _ip_clear.py    # kind logic (one file per kind)
│       └── ...
└── docs/                   # you are here
```

See [[patterns]] for the design pattern every department follows.

## Where to start contributing

Quickest win: pick a stubbed kind in [[upcoming-departments]] and port the logic from its source module. Same shape as the existing Research handlers (`_ip_clear.py` is a clean reference). One PR per kind.
