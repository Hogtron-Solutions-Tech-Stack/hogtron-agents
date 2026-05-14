---
tags: [hogtron, agents, department, future]
aliases: [future-departments, dept-expansion]
---

# Upcoming Departments

The 6 active departments (Creative, Research, Marketing, Sales, Operations, **Ledger**) are all live at Layer 1. This page tracks potential **future departments** that might graduate from being kinds inside an existing department.

## Candidate: Legal / Compliance

Currently the [[research-department|Research]] department's `ip_clear` kind owns blocklist + USPTO trademark checks. As the system grows, "compliance" may grow:

- **Trademark / IP**: existing `ip_clear`
- **Right-of-publicity**: living/dead public figures, name+likeness rules (currently in the same blocklist)
- **Privacy / data handling**: GDPR-ish rules if we ever serve EU clients
- **Terms-of-service**: per-platform rules (Etsy bans, Pinterest ToS, Shopify acceptable use)
- **Contract review**: scanning incoming MSAs for problematic clauses

**Promotion trigger**: if `ip_clear` graduates to gate Marketing copy + Sales contracts (not just Creative designs), it's likely time to split it out. Today it's only called by Factory's `vet_pending`.

## Candidate: Dedicated Canva Department

[[creative-department|Creative]] has a `canva_asset` kind stubbed today. As Canva work grows (logos, business cards, social posts, decks, proposal covers, brand kits), it might warrant its own dept — Canva has enough surface area to be its own discipline (templates, brand kits, design systems, content scheduling).

**Promotion trigger**: when `canva_asset` is doing 5+ distinct sub-kinds (logo, business card, IG post, deck, proposal cover, brand kit, ...) and they don't fit the single `kind="canva_asset"` interface cleanly.

## Candidate: Customer Success / Retention

Not represented today. Could absorb:
- Onboarding flows for new clients
- Health-check audits on existing client deliverables
- Churn-risk detection from engagement signals
- Renewal outreach
- Upsell suggestion engine

**Promotion trigger**: when we have 10+ active clients on retainer and manual retention is consuming significant time.

## ~~Candidate: Finance~~ → Promoted (Ledger)

Promoted to a real department on 2026-05-13 as [[ledger-department|Ledger]]. See that page for the implementation. Phase 1 covers P&L snapshots, cost watchdog state, and AR rollups; Phase 2 wires Slack alerts; Phase 3 wires AR follow-up dispatch back into Sales.

Out of scope (still): QuickBooks sync, tax prep, cash-flow projections. Those remain manual or get bolted on as new `LedgerKind` entries if they earn it.

## What about Engineering / IT?

You and Anthony cover this directly via Claude Code. No separate department needed. The "engineering work" the company needs is the work *building this system* — and that's not delegated to autonomous agents (yet).

If we eventually want autonomous engineering (refactors, bug fixes, dependency upgrades) — that's a Layer 3 CEO-loop activity that dispatches to Claude Code sessions, not a dedicated department.

## Re-evaluation rule

Per [[architecture#design-principles]] — promote a kind to its own department when:
1. It serves callers outside its current department's natural scope, AND
2. It has 3+ distinct kinds of work it does, AND
3. The current department's interface starts feeling forced.

Until all three are true, leave it where it is.
