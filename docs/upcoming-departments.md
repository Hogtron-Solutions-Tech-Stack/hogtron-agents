---
tags: [hogtron, agents, department, planned]
aliases: [marketing, sales, operations, upcoming]
---

# Upcoming Departments

The three not-yet-built department heads. Pattern follows [[creative-department|Creative]] and [[research-department|Research]] exactly: stateless dispatcher, one file per kind, provider-injection for IO.

## Marketing

> Words that sell. Listing copy, social posts, blog content, review responses, ad copy.

### Likely kinds

| Kind | What it does | Port source |
|---|---|---|
| `etsy_listing` | Write title (≤140 chars), description, 13 tags for a Printify product | FactoryHQ/agents/marketer.py |
| `social_post` | Compose a Pinterest/Instagram caption for a published shirt | FactoryHQ/agents/pinterester.py + future |
| `blog_post` | Long-form blog from a brief or topic | hogtron-dashboard Social-to-Blog Engine |
| `review_response` | Personalized response to a customer Google/Yelp review | dashboard AI Smart Review Responder |
| `ad_copy` | Etsy Ads / Google Ads short copy | future (Etsy Ads automation) |
| `email_outreach` | Cold outreach drafts to leads | future |

### Why separate from Sales

Marketing is *broadcast*: it produces content that goes to many people through a channel. Sales is *closing*: it operates on a specific prospect with intent to convert. Different rhythm (steady vs bursty), different content (general vs specific), different metrics (impressions vs close rate).

### Brief shape

Probably `MarketingBrief.kind`, `payload`, `context` — same as the others. Output: `MarketingAsset` with `primary_text`, `variants` (where applicable), `metadata` (channel, length, hashtags).

## Sales

> Closing motions. Proposals, follow-ups, pricing, contracts.

### Likely kinds

| Kind | What it does | Port source |
|---|---|---|
| `proposal` | Assemble a full client proposal (10-page template) | dashboard proposals + reference_proposal_template.md |
| `aggregator_audit_report` | Build the restaurant-aggregator audit deliverable | hogtron-dashboard/tools/aggregator_audit/generator.py |
| `follow_up` | Draft a follow-up message after no-response | future |
| `pricing_quote` | Generate a tiered quote given client size + scope | reference_pricing.md |
| `contract` | Fill in a contract template | future |

### Why this exists

Right now, proposal generation is Sean manually composing in Word / using dashboard templates. Promoting it to a department means: the Sales agent can take a lead + audit findings and produce a ready-to-review proposal autonomously. With human gate at "send" (rung 3 on the [[architecture#the-autonomy-ladder|autonomy ladder]]).

### Brief shape

Probably `SalesBrief` containing the lead + the prior research findings (SEO/GEO/aggregator audits). Output: `SalesAsset` with `primary_file` (PDF or Markdown), `email_draft`, `pricing_summary`.

## Operations

> Shipping things. Publishing, deploys, scheduled jobs, infra health, channel management.

### Likely kinds

| Kind | What it does | Port source |
|---|---|---|
| `publish_etsy` | Push a Printify-drafted product to Etsy | FactoryHQ/agents/marketer.py publish() |
| `publish_shopify` | Same but to the new Shopify channel | future (Shopify just added 2026-05-12) |
| `publish_pinterest` | Cross-post a published listing to Pinterest boards | FactoryHQ/agents/pinterester.py |
| `render_video` | Ken Burns video from product mockups | FactoryHQ/agents/distributor.py |
| `deploy_mockup` | Push a client mockup to the Railway gallery | hogtron-dashboard mockup deploy |
| `deploy_proposal` | Publish a client proposal to its share URL | dashboard payments + proposal share |
| `printify_upload` | Upload art → create draft product (currently in FactoryHQ designer.py) | FactoryHQ/agents/designer.py upload() |

### Why this exists

Today, "publishing" logic is scattered: FactoryHQ designer.py has Printify upload, marketer.py has Etsy publish, distributor.py has video rendering, dashboard has mockup deploy + proposal deploy. They all do the same kind of work: take an internal artifact, push it to an external system, update internal state.

Operations consolidates that. Plus it's the natural home for **channel-rotating** logic: if Shopify becomes a better channel than Etsy for some shirts, the Marketing dept doesn't change — Operations decides which channel to publish to.

### Brief shape

Probably `OperationsBrief` with a target (Etsy / Shopify / Pinterest / Railway / etc.) and an artifact reference. Output: `OperationsResult` with `external_id`, `external_url`, `success`, `cost_estimate`.

## Build order

Suggested sequence (subject to revisit when we get there):

1. **Marketing first.** Most reusable; most Layer 2 / Layer 3 work depends on copy generation. Etsy listings, social posts, review responses are the highest-volume content needs.
2. **Sales second.** Needs Marketing for the prose pieces; once Marketing exists, Sales is mostly assembly + template work.
3. **Operations last.** Most coupled to external services (Printify, Etsy, Shopify, Railway). Worth waiting until we know which channels we're seriously committing to (Shopify is brand new as of 2026-05-12 — give it some time before consolidating publish logic).

After all 5 are at Layer 1, we move to Layer 2 spike on **Research** (cheapest mistakes) and then the CEO loop. See [[architecture#the-3-layer-model]].
