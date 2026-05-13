"""CEO loop internals — SYSTEM_PROMPT + dept tool wrappers + result types.

Same agent_loop substrate as Layer 2, but at Layer 3 each tool call IS
ITSELF an agent loop. One CEO directive can cascade into many dept-level
model turns. Costs add up — set max_iterations conservatively.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .._shared.agent_loop import (
    AgentTool, run_agent_loop, estimate_cost_usd,
)


SYSTEM_PROMPT = """You are the CEO interface for HogTron Solutions — speaking
with Sean and Anthony's voice. Two product lines:

  1. HogTron Factory (CottonForgeBoutique) — autonomous POD shirt
     business on Etsy. Algorithmic, high-volume, IP-sensitive.
  2. HogTron Agency — freelance web/automation consulting. SEO/GEO
     audits, mockups, proposals, client retainers.

YOUR DEPARTMENTS (each is itself an autonomous agent)
  - research(directive): Intel. Find trends, leads, IP-clear phrases,
    SEO/GEO audits, restaurant aggregator platform detection.
  - creative(directive): Visual production. Shirts, mockups, PDFs,
    proposal covers, Canva assets. (Today: shirt design only.)
  - marketing(directive): Words. Etsy listings, Pinterest pin copy.
    (More kinds shipping over time.)
  - sales(directive): Closing motions for specific prospects. Aggregator
    audit reports today. (Proposals + quotes coming.)
  - operations(directive): SHIPS THINGS. Printify uploads, Etsy publish,
    Pinterest pins, video renders. Every action has real-world cost +
    visibility. Treat with care.

OPERATING PRINCIPLES
- BE EFFICIENT WITH BUDGET. Every department call costs tokens + maybe
  external API spend. Don't dispatch what isn't needed.
- DEPARTMENTS CAN CHAIN: A Father's-Day-shirts directive typically flows
  research(find IP-clear phrases) -> creative(design each) ->
  marketing(write listings + pin copy) -> operations(upload to Printify;
  HOLD publishing for human approval per the autonomy ladder).
- AUTONOMY LADDER (rung 0 today): publish_* actions on Operations should
  STOP at the draft/ready stage. The human reviews mockups before
  anything goes live to a customer.
- BE HONEST. If a department returns thin results, errors, or partial
  success, surface it. Don't paper over it.
- WHEN A DIRECTIVE IS AMBIGUOUS: make the most reasonable interpretation
  and proceed — don't ask clarifying questions. Sean + Anthony will
  redirect on the next directive.

OUTPUT FORMAT
Your final response is what will appear in Sean + Anthony's daily Journal.
Structure it as:
  - **What I did**: high-level chain (3-7 bullets)
  - **What you'll find**: concrete deliverables produced (file paths,
    URLs, counts) — what they can actually inspect
  - **Open items**: human-approval blockers, ambiguities, downstream
    risks worth flagging
  - **Total cost**: Claude + external API spend for this directive

Keep it tight. No filler. The Journal is read daily; the read time
matters."""


@dataclass
class DeptCallSummary:
    """One department's outcome from a CEO call."""
    department: str
    directive: str
    success: bool
    summary: str
    iterations: int
    cost_usd: float
    ops_cost_usd: float = 0.0
    tool_calls_count: int = 0
    # The Anthropic model the nested dept actually ran on. Captured at
    # dispatch time from the dept's run_autonomous default so telemetry
    # downstream (Bridge OVERSEER panel, dept_runs.model) can render the
    # right tier badge per dept-call.
    model: Optional[str] = None


@dataclass
class CEOResult:
    directive: str
    summary: str                             # the journal-ready text
    dept_calls: list[DeptCallSummary]
    success: bool
    iterations: int
    duration_sec: float
    input_tokens: int                        # CEO-level only (dept tokens are nested)
    output_tokens: int
    cost_usd: float                          # CEO + all nested dept Claude tokens
    ops_cost_usd: float                      # nested Operations real-world spend
    stop_reason: str
    error: Optional[str] = None


def build_tools(
    *,
    research, creative, marketing, sales, operations,
    anthropic_api_key: str,
    dept_max_iterations: int = 10,
    should_cancel=None,
) -> tuple[list[DeptCallSummary], list[AgentTool]]:
    """Wrap each dept's run_autonomous as a CEO-level tool.

    `should_cancel` is forwarded to each nested dept run so the Bridge's
    Cancel button reaches all the way down into in-flight dept loops.
    """
    dept_calls: list[DeptCallSummary] = []

    def _wrap(dept_name: str, dept_instance, attr_name: str):
        import inspect
        method = getattr(dept_instance, "run_autonomous")
        # Capture whatever the dept declares as its default model so the
        # CEO's DeptCallSummary can record exactly what each nested call
        # ran on (Sonnet for all 5 depts today; tracked via the dept's
        # own signature so updates stay in sync without coupling here).
        _sig = inspect.signature(method)
        _model_param = _sig.parameters.get("model")
        _default_model = _model_param.default if _model_param else None

        def handler(directive: str) -> dict:
            kwargs = {
                "anthropic_api_key": anthropic_api_key,
                "max_iterations":    dept_max_iterations,
            }
            # Only forward should_cancel if the dept accepts it. Older
            # depts in mixed-version dev envs won't have the param yet.
            if "should_cancel" in _sig.parameters and should_cancel is not None:
                kwargs["should_cancel"] = should_cancel
            result = method(directive, **kwargs)
            # Standardize across dept-specific AutonomousResult shapes
            ops_cost = getattr(result, "ops_cost_usd", 0.0)
            summary = DeptCallSummary(
                department=dept_name, directive=directive,
                success=result.success, summary=result.summary,
                iterations=result.iterations, cost_usd=result.cost_usd,
                ops_cost_usd=ops_cost, tool_calls_count=len(result.tool_calls),
                model=_default_model,
            )
            dept_calls.append(summary)
            return {
                "department": dept_name,
                "success": result.success,
                "summary": result.summary[:3000],
                "iterations": result.iterations,
                "tool_calls": len(result.tool_calls),
                "cost_usd": round(result.cost_usd, 4),
                "ops_cost_usd": round(ops_cost, 4),
                "error": result.error,
            }
        return handler

    def _tool(name: str, dept_name: str, desc: str, dept_instance, attr: str) -> AgentTool:
        return AgentTool(
            name=name, description=desc,
            input_schema={
                "type": "object",
                "properties": {
                    "directive": {
                        "type": "string",
                        "description": f"Natural-language directive for {dept_name}. Be specific about deliverables.",
                    },
                },
                "required": ["directive"],
            },
            handler=_wrap(dept_name, dept_instance, attr),
        )

    return dept_calls, [
        _tool("research", "Research",
              "Dispatch Research dept (trend scraping, IP clearance, lead "
              "discovery, SEO/GEO audits, platform-presence detection). "
              "Returns {summary, iterations, tool_calls, cost_usd}.",
              research, "do"),
        _tool("creative", "Creative",
              "Dispatch Creative dept (shirt design today; pdf_page / "
              "mockup / proposal_cover / canva_asset stubbed). Returns "
              "{summary, iterations, tool_calls, cost_usd}.",
              creative, "design"),
        _tool("marketing", "Marketing",
              "Dispatch Marketing dept (Etsy listings, Pinterest pin copy "
              "today). Returns {summary, iterations, tool_calls, cost_usd}.",
              marketing, "write"),
        _tool("sales", "Sales",
              "Dispatch Sales dept (aggregator audit reports today; "
              "proposal/follow_up/pricing_quote/contract stubbed). Returns "
              "{summary, iterations, tool_calls, cost_usd}.",
              sales, "build"),
        _tool("operations", "Operations",
              "Dispatch Operations dept. EVERY OPERATIONS KIND HAS REAL "
              "EXTERNAL SIDE EFFECTS. Use directives that respect the "
              "autonomy ladder (rung 0: hold publish_* without explicit "
              "authorization). Returns {summary, iterations, tool_calls, "
              "cost_usd, ops_cost_usd}.",
              operations, "do"),
    ]


def run_autonomous(
    ceo_instance,
    directive: str,
    *,
    anthropic_api_key: str,
    model: str = "claude-opus-4-7",
    max_iterations: int = 8,
    dept_max_iterations: int = 10,
    progress_callback=None,
    should_cancel=None,
) -> CEOResult:
    dept_calls, tools = build_tools(
        research=ceo_instance.research,
        creative=ceo_instance.creative,
        marketing=ceo_instance.marketing,
        sales=ceo_instance.sales,
        operations=ceo_instance.operations,
        anthropic_api_key=anthropic_api_key,
        dept_max_iterations=dept_max_iterations,
        should_cancel=should_cancel,
    )

    result = run_agent_loop(
        system=SYSTEM_PROMPT,
        user_message=directive,
        tools=tools,
        api_key=anthropic_api_key,
        model=model,
        max_iterations=max_iterations,
        telemetry=ceo_instance.telemetry,
        role="ceo",
        progress_callback=progress_callback,
        should_cancel=should_cancel,
    )

    # Total cost = CEO tokens + all nested dept Claude tokens
    ceo_tokens_cost = estimate_cost_usd(model, result.input_tokens, result.output_tokens)
    nested_claude_cost = sum(d.cost_usd for d in dept_calls)
    nested_ops_cost = sum(d.ops_cost_usd for d in dept_calls)

    return CEOResult(
        directive=directive,
        summary=result.final_message,
        dept_calls=dept_calls,
        success=result.success,
        iterations=result.iterations,
        duration_sec=result.duration_sec,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_usd=ceo_tokens_cost + nested_claude_cost,
        ops_cost_usd=nested_ops_cost,
        stop_reason=result.stop_reason,
        error=result.error,
    )
