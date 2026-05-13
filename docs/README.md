---
tags: [hogtron, agents, index]
aliases: [docs, agent-docs]
---

# HogTron Agentic System — Docs

Start here. Everything in this folder is plain Markdown with wiki-style links so it works as an Obsidian vault for RAG.

## Read in this order

1. [[overview]] — what the system is and why we built it (for Anthony, or anyone new)
2. [[architecture]] — the 3-layer model (departments → agent loops → CEO loop) and the autonomy ladder
3. [[patterns]] — how briefs, findings, dispatchers, and provider-injection work in code
4. [[creative-department]] — Creative dept (5 kinds, shirt piloted)
5. [[research-department]] — Research dept (7 kinds, all ported)
6. [[marketing-department]] — Marketing dept (6 kinds, etsy_listing piloted)
7. [[sales-department]] — Sales dept (5 kinds, aggregator_audit_report piloted)
8. [[operations-department]] — Operations dept (7 kinds, printify_upload piloted)
9. [[upcoming-departments]] — future expansion candidates (Legal/Compliance, dedicated Canva)
10. [[infra]] — Supabase + Railway + external accounts (Canva, Shopify, Etsy, etc.)
11. [[roadmap]] — what's shipped, what's next

## Tags glossary

- `#department` — pages about a specific department head
- `#pattern` — design patterns used across departments
- `#infra` — infrastructure / hosting / DB / external services
- `#decision` — architectural decisions worth preserving
- `#ip-guardrail` — anything related to trademark / brand IP protection

## TL;DR for the impatient

We have 13 product-line-specific agent scripts spread across two repos (FactoryHQ + hogtron-dashboard). They duplicate each other (shirt pipeline and PDF pipeline both have their own researcher/designer/marketer). We're consolidating them into **5 department heads** (Creative, Research, Marketing, Sales, Operations) that any product line can call. Sean + Anthony sit above as CEOs.

The departments live in a shared pip-installable package: `C:\Users\sbilg\Code\hogtron-agents\`. Both repos import from it. New product lines plug in for free.

Status: **All 5 departments scaffolded** with 30 kinds total. 5 piloted with real handlers (shirt, ip_clear/geo_audit/seo_audit/platform_presence + 3 more in Research, etsy_listing, aggregator_audit_report, printify_upload). Remaining kinds stubbed with port-target pointers. Layer 1 of the [[architecture|3-layer model]] is complete in shape.
