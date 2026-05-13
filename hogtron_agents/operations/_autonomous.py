"""Operations department — Layer 2 autonomous agent loop.

DIFFERENT FROM OTHER DEPTS: every Operations kind has real-world side
effects. Printify draft creation, Etsy publish ($0.20 + 6.5% commission),
Pinterest pin creation, MP4 rendering. The system prompt is more explicit
about budget discipline + the autonomy ladder per kind.

For safety today: Layer 3 callers should default `dry_run=True` and
inspect the plan before flipping to real execution. We don't enforce
that here (an agent can be told to ship things), but the SYSTEM_PROMPT
biases the model toward conservative behavior.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .briefs import OperationsBrief, OperationsResult
from .._shared.agent_loop import (
    AgentResult, AgentTool, run_agent_loop, estimate_cost_usd,
)


SYSTEM_PROMPT = """You are the Operations department of HogTron Solutions.

YOUR ROLE
- You report to the CEOs (Sean + Anthony). You ship artifacts out to
  external systems (Printify, Etsy, Shopify, Pinterest, Railway) and
  perform local compute (video rendering).
- EVERY tool call here has real-world consequences. A published Etsy
  listing costs money and appears publicly. A Pinterest pin can't be
  unpublished cleanly. Take your time. Don't ship anything the
  directive doesn't clearly authorize.

YOUR TOOLS (with cost + reversibility per call)
  - printify_upload: FREE. Creates a draft product. Reversible (delete
    via Printify UI). Use freely.
  - publish_etsy: $0.20/listing fee + 6.5% transaction commission on
    sales. Visible publicly. Reversible (unpublish from Etsy) but
    a visible action. Confirm intent before calling.
  - publish_pinterest: FREE (Pinterest API). Visible. Reversible
    (delete pin via API or UI). Confirm intent before calling at
    scale.
  - render_video: FREE (local ffmpeg). No external visibility. Use freely.

AUTONOMY LADDER (HogTron policy as of 2026-05-12, rung 0):
- All `publish_*` calls should wait for human approval. If the directive
  doesn't include explicit authorization to publish ("ship them to
  Etsy now", "publish the queue", etc.), STOP after printify_upload
  / render_video and summarize what would happen next.
- `printify_upload` and `render_video` are safe to call freely under
  any directive that mentions designs needing prep.

OUTPUT FORMAT
End your turn with:
  - What you executed (with external IDs + URLs)
  - What you DID NOT execute (and why — "awaiting publish approval")
  - Total cost_estimate_usd
  - Anything the CEO should know before the next directive"""


@dataclass
class AutonomousResult:
    directive: str
    summary: str
    tool_calls: list[dict]
    results: list[OperationsResult]
    success: bool
    iterations: int
    duration_sec: float
    input_tokens: int
    output_tokens: int
    cost_usd: float        # Claude tokens
    ops_cost_usd: float    # real-world spend (Etsy fees, etc.)
    stop_reason: str
    error: Optional[str] = None


def build_tools(operations_instance) -> tuple[list[OperationsResult], list[AgentTool]]:
    results: list[OperationsResult] = []

    def _call(kind: str, payload: dict, context: Optional[dict] = None) -> dict:
        r = operations_instance.do(OperationsBrief(
            kind=kind, payload=payload, context=context or {},
            requester="operations.autonomous",
        ))
        results.append(r)
        return {
            "kind": r.kind, "success": r.success,
            "external_id": r.external_id, "external_url": r.external_url,
            "payload": r.payload, "metadata": r.metadata,
            "cost_estimate_usd": r.cost_estimate_usd, "error": r.error,
        }

    return results, [
        AgentTool(
            name="printify_upload",
            description=(
                "Upload art + create a Printify DRAFT product. Free, reversible. "
                "Returns {image_id, product_id, mockup_url}. "
                "shop_id / variant_ids / blueprint_id / print_provider_id all "
                "fall back to the configured env (PRINTIFY_SHOP_ID, "
                "PRINTIFY_DEFAULT_VARIANT_IDS, etc.) — omit them unless "
                "the directive specifies a non-default shop."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "art_local_path": {"type": "string"},
                    "file_name": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "placement_y": {"type": "number", "default": 0.35},
                    "shop_id": {
                        "type": "string",
                        "description": "Optional. Defaults to env PRINTIFY_SHOP_ID.",
                    },
                    "variant_ids": {
                        "type": "array", "items": {"type": "integer"},
                        "description": "Optional. Defaults to env PRINTIFY_DEFAULT_VARIANT_IDS.",
                    },
                    "blueprint_id": {
                        "type": "integer",
                        "description": "Optional. Defaults to env PRINTIFY_BLUEPRINT_ID or 384.",
                    },
                    "print_provider_id": {
                        "type": "integer",
                        "description": "Optional. Defaults to env PRINTIFY_PRINT_PROVIDER_ID or 29.",
                    },
                },
                "required": ["art_local_path", "file_name", "title", "description"],
            },
            handler=lambda **kw: _call("printify_upload", kw),
        ),
        AgentTool(
            name="publish_etsy",
            description=(
                "Push an existing Printify draft to its linked Etsy shop. "
                "PUBLIC, costs $0.20 + 6.5% commission. Per autonomy ladder, "
                "ONLY call when the directive explicitly authorizes publishing. "
                "shop_id falls back to env PRINTIFY_SHOP_ID."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "product_id": {"type": "string"},
                    "shop_id": {
                        "type": "string",
                        "description": "Optional. Defaults to env PRINTIFY_SHOP_ID.",
                    },
                },
                "required": ["product_id"],
            },
            handler=lambda product_id, shop_id=None: _call(
                "publish_etsy",
                {"product_id": product_id, "shop_id": shop_id} if shop_id
                else {"product_id": product_id},
            ),
        ),
        AgentTool(
            name="publish_pinterest",
            description=(
                "Create a Pinterest pin linking to a destination (typically "
                "an Etsy listing). Free, visible. Per autonomy ladder, ONLY "
                "call when the directive explicitly authorizes publishing. "
                "board_id falls back to env PINTEREST_BOARD_ID."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "link": {"type": "string"},
                    "image_url": {"type": "string"},
                    "alt_text": {"type": "string"},
                    "board_id": {
                        "type": "string",
                        "description": "Optional. Defaults to env PINTEREST_BOARD_ID.",
                    },
                },
                "required": ["title", "description", "link", "image_url"],
            },
            handler=lambda **kw: _call("publish_pinterest", kw),
        ),
        AgentTool(
            name="render_video",
            description=(
                "Compose a 1080x1920 vertical MP4 from a mockup + phrase via "
                "ffmpeg. Free (local). No external visibility. Returns "
                "{path, width, height, duration_sec}."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "mockup_path": {"type": "string"},
                    "phrase": {"type": "string"},
                    "design_id": {"type": "string"},
                    "duration_sec": {"type": "integer", "default": 5},
                },
                "required": ["mockup_path", "phrase"],
            },
            handler=lambda **kw: _call("render_video", kw),
        ),
    ]


def run_autonomous(operations_instance, directive, *, anthropic_api_key,
                   model="claude-opus-4-7", max_iterations=10) -> AutonomousResult:
    results, tools = build_tools(operations_instance)
    agent_result = run_agent_loop(
        system=SYSTEM_PROMPT, user_message=directive, tools=tools,
        api_key=anthropic_api_key, model=model, max_iterations=max_iterations,
        telemetry=operations_instance.telemetry, role="operations.autonomous",
    )
    ops_cost = sum(r.cost_estimate_usd or 0 for r in results)
    return AutonomousResult(
        directive=directive, summary=agent_result.final_message,
        tool_calls=[{"tool": tc.tool, "input": tc.input,
                     "elapsed_sec": tc.elapsed_sec, "error": tc.error}
                    for tc in agent_result.tool_calls],
        results=results, success=agent_result.success,
        iterations=agent_result.iterations, duration_sec=agent_result.duration_sec,
        input_tokens=agent_result.input_tokens, output_tokens=agent_result.output_tokens,
        cost_usd=estimate_cost_usd(model, agent_result.input_tokens, agent_result.output_tokens),
        ops_cost_usd=ops_cost,
        stop_reason=agent_result.stop_reason, error=agent_result.error,
    )
