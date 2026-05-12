---
tags: [hogtron, agents, index]
aliases: [docs, agent-docs]
---

# HogTron Agentic System — Docs

Start here. Everything in this folder is plain Markdown with [[wiki-style]] links so it works as an Obsidian vault for RAG.

## Read in this order

1. [[overview]] — what the system is and why we built it (for Anthony, or anyone new)
2. [[architecture]] — the 3-layer model (departments → agent loops → CEO loop) and the autonomy ladder
3. [[patterns]] — how briefs, findings, dispatchers, and provider-injection work in code
4. [[creative-department]] — the Creative department head (built first, full deep-dive)
5. [[research-department]] — the Research department head (built second, 7 kinds)
6. [[upcoming-departments]] — Marketing, Sales, Operations (planned)
7. [[infra]] — Supabase + Railway + external accounts (Canva, Shopify, Etsy, etc.)
8. [[roadmap]] — what's shipped, what's next

## Tags glossary

- `#department` — pages about a specific department head
- `#pattern` — design patterns used across departments
- `#infra` — infrastructure / hosting / DB / external services
- `#decision` — architectural decisions worth preserving
- `#ip-guardrail` — anything related to trademark / brand IP protection

## TL;DR for the impatient

We have 13 product-line-specific agent scripts spread across two repos (FactoryHQ + hogtron-dashboard). They duplicate each other (shirt pipeline and PDF pipeline both have their own researcher/designer/marketer). We're consolidating them into **5 department heads** (Creative, Research, Marketing, Sales, Operations) that any product line can call. Sean + Anthony sit above as CEOs.

The departments live in a shared pip-installable package: `C:\Users\sbilg\Code\hogtron-agents\`. Both repos import from it. New product lines plug in for free.

Status: Creative + Research shipped. Marketing, Sales, Operations queued.
