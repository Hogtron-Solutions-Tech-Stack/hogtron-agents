"""Research department — Layer 2 autonomous agent loop.

Wraps the 7 Layer 1 kinds as tools, gives Claude a system prompt that
explains the dept's job + IP constraints, and runs an agent loop that
chains kinds in response to a CEO-style directive.

Pilot for Layer 2. Same pattern will be applied to Marketing/Sales/
Operations/Creative once this is validated.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .briefs import ResearchBrief, ResearchFinding
from .._shared.agent_loop import (
    AgentResult, AgentTool, run_agent_loop, estimate_cost_usd,
)


SYSTEM_PROMPT = """You are the Research department of HogTron Solutions.

YOUR ROLE
- You report to the CEOs (Sean + Anthony). You receive natural-language
  directives and chain Research tools to fulfill them.
- You're the company's intel surface: market trends, IP clearance, lead
  discovery, SEO/GEO audits, restaurant aggregator platform detection.

YOUR TOOLS
You have 7 Layer 1 research kinds available as tools. Each is stateless
and returns a structured ResearchFinding. Use them in whatever order
makes sense:
  - trend_signals: scrape Etsy via SerpAPI for raw market signals (titles + URLs)
  - cluster_concepts: Claude clusters raw signals into concepts + phrase candidates
  - ip_clear: blocklist + USPTO trademark check on a candidate phrase
  - find_leads: Google Places + OSM Overpass lead scraping
  - seo_audit: scrape + LLM-score on-page SEO pillars for a URL
  - geo_audit: GEO auditor service for a URL
  - platform_presence: site-restricted Google queries to detect restaurant
    aggregator listings (DoorDash/UberEats/Grubhub/Slice)

OPERATING PRINCIPLES
- Be efficient. The CEOs are paying for every token + every API call.
  Don't run trend_signals 10 times when 1 will do. Don't ip_clear phrases
  one at a time when you can batch.
- Be honest. If a tool errors or returns thin data, report it. Don't
  pretend success.
- IP guardrail is non-negotiable. For POD/shirt work, every candidate
  phrase MUST pass ip_clear before being included in a final output.
- When a directive is ambiguous, make the most reasonable interpretation
  and proceed — don't ask clarifying questions, just decide. If the
  decision turns out wrong, the next directive will correct it.

OUTPUT FORMAT
When you've fulfilled the directive (or determined you can't), end your
turn with a clear text summary:
  - What you did (which tools, how many calls)
  - What you found (counts, examples, blockers)
  - Recommendations for the CEO (if any)
Keep the summary tight. No filler. Bullet points are fine."""


@dataclass
class AutonomousResult:
    """Full outcome of a Research.run_autonomous() call."""
    directive: str
    summary: str                         # the model's final text turn
    tool_calls: list[dict]               # one entry per tool invocation
    findings: list[ResearchFinding]      # ResearchFindings the agent produced
    success: bool
    iterations: int
    duration_sec: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    stop_reason: str
    error: Optional[str] = None


def build_tools(research_instance) -> list[AgentTool]:
    """Build the AgentTool list wrapping Research's 7 kinds.

    Each tool's handler closes over `research_instance` so it inherits
    the configured tm_provider, telemetry, etc.
    """
    findings: list[ResearchFinding] = []

    def _call(kind: str, payload: dict, context: Optional[dict] = None) -> dict:
        brief = ResearchBrief(
            kind=kind, payload=payload, context=context or {},
            requester="research.autonomous",
        )
        finding = research_instance.do(brief)
        findings.append(finding)
        # Return a compact dict the model can read. Strip massive payloads
        # (e.g. seo_audit's raw scrape body) to keep context tight.
        return _summarize_finding(finding)

    return findings, [
        AgentTool(
            name="trend_signals",
            description=(
                "Scrape Etsy via SerpAPI for raw market signals. Returns "
                "{n_signals, signals: [{title, url, source_query}]}. Use to "
                "feed cluster_concepts. Costs ~1 SerpAPI credit per query."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "queries": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Search terms (e.g. ['funny coffee shirt', 'teacher life shirt']). 1-10 queries.",
                    },
                    "limit_per_query": {
                        "type": "integer",
                        "description": "Max signals per query. Default 20.",
                        "default": 20,
                    },
                },
                "required": ["queries"],
            },
            handler=lambda queries, limit_per_query=20: _call(
                "trend_signals",
                {"queries": queries, "source": "etsy", "limit_per_query": limit_per_query},
            ),
        ),
        AgentTool(
            name="cluster_concepts",
            description=(
                "Claude clusters raw market signals into POD shirt concepts "
                "with 3-8 phrase candidates each. Returns {n_concepts, "
                "n_phrases, concepts: [{concept, audience, saturation, "
                "seasonal_window, phrases}]}. Costs ~$0.05-0.20 in Claude tokens."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "signals": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Raw signal dicts from trend_signals. Can be empty.",
                    },
                    "max_concepts": {"type": "integer", "default": 5},
                    "seasonal_hint": {
                        "type": "string",
                        "description": "Optional text about upcoming commercial windows.",
                    },
                },
                "required": ["signals"],
            },
            handler=lambda signals, max_concepts=5, seasonal_hint="": _call(
                "cluster_concepts",
                {"signals": signals, "max_concepts": max_concepts, "seasonal_hint": seasonal_hint},
            ),
        ),
        AgentTool(
            name="ip_clear",
            description=(
                "Blocklist + USPTO trademark check on a candidate phrase for "
                "POD shirt use. Returns {status: 'clear'|'blocked'|'tm_hit', "
                "marks: [...], reason}. CALL THIS BEFORE INCLUDING ANY PHRASE "
                "IN A FINAL OUTPUT — it's the company's IP guardrail."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "phrase": {"type": "string", "description": "Candidate shirt phrase."},
                },
                "required": ["phrase"],
            },
            handler=lambda phrase: _call("ip_clear", {"phrase": phrase}),
        ),
        AgentTool(
            name="find_leads",
            description=(
                "Find local businesses by industry + location via Google Places "
                "(or OSM fallback). Returns {n_leads, source, leads: [...]}."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "industry": {"type": "string"},
                    "zip": {"type": "string"},
                    "city": {"type": "string"},
                    "state": {"type": "string"},
                    "county": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["industry"],
            },
            handler=lambda industry, limit=20, zip=None, city=None, state=None, county=None: _call(
                "find_leads",
                {"industry": industry, "limit": limit, "zip": zip or "",
                 "city": city or "", "state": state or "", "county": county or ""},
            ),
        ),
        AgentTool(
            name="seo_audit",
            description=(
                "Scrape + LLM-score 5 on-page SEO pillars for a URL. Returns "
                "{overall_score, overall_grade, pillars, priority_action}."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "provider": {
                        "type": "string",
                        "enum": ["gemini", "anthropic", "xai", "local"],
                        "default": "anthropic",
                    },
                },
                "required": ["url"],
            },
            handler=lambda url, provider="anthropic": _call(
                "seo_audit", {"url": url}, {"provider": provider},
            ),
        ),
        AgentTool(
            name="geo_audit",
            description=(
                "GEO (Generative Engine Optimization) audit via the deployed "
                "geo-auditor service. Returns {overall_score, overall_grade, "
                "pillars, priority_action}."
            ),
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            handler=lambda url: _call("geo_audit", {"url": url}),
        ),
        AgentTool(
            name="platform_presence",
            description=(
                "Detect which delivery aggregator platforms a restaurant is "
                "listed on (DoorDash, UberEats, Grubhub, Slice). Returns "
                "{n_listed, n_missing, results: {platform: {listed, url, ...}}}."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "city": {"type": "string"},
                    "state": {"type": "string"},
                    "platforms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Subset of [doordash, ubereats, grubhub, slice]. Default all.",
                    },
                },
                "required": ["name"],
            },
            handler=lambda name, city="", state="", platforms=None: _call(
                "platform_presence",
                {"name": name, "city": city, "state": state,
                 "platforms": platforms or ["doordash", "ubereats", "grubhub", "slice"]},
            ),
        ),
    ]


def _summarize_finding(finding: ResearchFinding) -> dict:
    """Trim a ResearchFinding to what the agent needs to see.

    The full ResearchFinding can be huge (seo_audit returns full pillar
    detail + scraped body). We want the agent to see status + summary
    metadata and only the highest-value bits of payload, so its context
    window stays tight across many tool calls.
    """
    base = {"status": finding.status, "reason": finding.reason,
            "metadata": finding.metadata}

    kind = finding.kind
    p = finding.payload or {}

    if kind == "trend_signals":
        signals = p.get("signals", [])
        return {**base, "n_signals": len(signals),
                "signals": [{"title": s.get("title"), "url": s.get("url"),
                             "source_query": s.get("source_query")} for s in signals[:50]]}
    if kind == "cluster_concepts":
        concepts = p.get("concepts", [])
        return {**base, "n_concepts": len(concepts),
                "n_phrases": sum(len(c.get("phrases", [])) for c in concepts),
                "concepts": concepts, "reasoning": p.get("reasoning")}
    if kind == "ip_clear":
        if finding.status == "tm_hit":
            marks = p.get("marks", [])
            return {**base, "n_marks": len(marks),
                    "marks": [{"serial": m.get("serial_number"),
                               "text": m.get("mark_text")} for m in marks[:5]]}
        return {**base, "matches": p.get("matches")}
    if kind == "find_leads":
        leads = p.get("leads", [])
        return {**base, "n_leads": len(leads),
                "leads": [{"name": l.get("business_name"),
                           "phone": l.get("phone"),
                           "website": l.get("website"),
                           "city": l.get("city"),
                           "state": l.get("state")} for l in leads[:20]]}
    if kind in ("seo_audit", "geo_audit"):
        audit = p.get("audit", {})
        return {**base, "overall_score": audit.get("overall_score"),
                "overall_grade": audit.get("overall_grade"),
                "priority_action": audit.get("priority_action"),
                "one_line_verdict": audit.get("one_line_verdict")}
    if kind == "platform_presence":
        results = p.get("results", {})
        return {**base, "results": {
            slug: {"listed": r.get("listed"), "confidence": r.get("confidence"),
                   "url": r.get("url")}
            for slug, r in results.items()
        }}
    return {**base, "payload": p}


def run_autonomous(
    research_instance,
    directive: str,
    *,
    anthropic_api_key: str,
    model: str = "claude-sonnet-4-6",
    max_iterations: int = 6,
    progress_callback=None,
    should_cancel=None,
) -> AutonomousResult:
    """Run the Research department's agent loop on a natural-language directive.

    `research_instance` should be a Research() with tm_provider, telemetry,
    etc. already injected — its kinds will be exposed to the agent.
    """
    findings, tools = build_tools(research_instance)

    result: AgentResult = run_agent_loop(
        system=SYSTEM_PROMPT,
        user_message=directive,
        tools=tools,
        api_key=anthropic_api_key,
        model=model,
        max_iterations=max_iterations,
        telemetry=research_instance.telemetry,
        role="research.autonomous",
        progress_callback=progress_callback,
        should_cancel=should_cancel,
    )

    return AutonomousResult(
        directive=directive,
        summary=result.final_message,
        tool_calls=[
            {"tool": tc.tool, "input": tc.input, "elapsed_sec": tc.elapsed_sec,
             "error": tc.error,
             "result_summary": _abbrev(tc.result)}
            for tc in result.tool_calls
        ],
        findings=findings,
        success=result.success,
        iterations=result.iterations,
        duration_sec=result.duration_sec,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_usd=estimate_cost_usd(model, result.input_tokens, result.output_tokens),
        stop_reason=result.stop_reason,
        error=result.error,
    )


def _abbrev(result: Any) -> str:
    """Shorten a tool result for the AutonomousResult log."""
    import json
    s = json.dumps(result, default=str)
    return s if len(s) <= 300 else s[:297] + "..."
