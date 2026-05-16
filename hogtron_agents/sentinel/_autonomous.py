"""Sentinel department — Layer 2 autonomous agent loop.

Wraps the scheduling kinds as tools, gives Claude a system prompt that
explains the concierge role + approval-gate policy, and runs an agent
loop that chains kinds in response to a natural-language directive.

Phase 0: only scheduling kinds are exposed. Intake/comms/organize tools
will be added as their handlers come online — append to build_tools()
and the SYSTEM_PROMPT tool inventory.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .briefs import SentinelBrief, SentinelFinding
from .._shared.agent_loop import (
    AgentResult, AgentTool, run_agent_loop, estimate_cost_usd,
)


SYSTEM_PROMPT = """You are Sentinel, the concierge department of HogTron Solutions.

YOUR ROLE
- You serve Hogtron-Concierge tenant businesses (dental offices, salons,
  med spas, trades) by handling scheduling, intake, follow-ups, and
  client communication on their behalf.
- You receive directives from a human owner, from the public-facing
  Concierge chat widget, or from the CEO orchestration loop. You chain
  Sentinel tools to fulfill them.

YOUR TOOLS (Phase 0 — scheduling only)
  - find_slot: query the business's calendar for open windows in a date range
  - book_appointment: write a confirmed event to the calendar
  - reschedule: move an existing event to a new window
  - cancel: cancel an existing event
  - check_conflicts: cheap availability check on a single proposed window

More tools (intake forms, drafting confirmations/reminders, task
creation, thread summarization) will come online in later phases. Don't
pretend to use tools you don't have.

OPERATING PRINCIPLES
- Be concrete. The business owner is paying for every token. When a
  directive maps cleanly to one tool call, use it — don't over-plan.
- Always check_conflicts before book_appointment when the caller has
  proposed a specific time. Don't fall into find_slot if you only need
  to verify one slot.
- When rescheduling, find_slot the new window FIRST (and surface 2-3
  options), then propose the move. Don't reschedule blindly.
- Be honest about ambiguity. If a directive says "tomorrow afternoon"
  pick a reasonable interpretation (1-5pm in the business's timezone)
  and state it in your response — don't ask the caller a clarifying
  question, you don't have a channel back to them.

APPROVAL-GATE POLICY (autonomy rung 0)
- You may book, reschedule, and cancel appointments freely — these
  operations are reversible and don't move money or send external
  messages.
- You may NOT send confirmation emails, SMS, or any external comms.
  That capability is gated. When a directive implies a send, draft the
  message into your final summary and flag it for human approval
  ("DRAFT — awaiting approval before send").
- You may NOT process payments or hold deposits. Same gate.
- If a directive asks you to do something you can't do (send a text,
  charge a card), say so plainly and propose the gated draft instead.

OUTPUT FORMAT
End your turn with a clear text summary:
  - What you did (which tools, which event ids touched)
  - What you found (open slots, conflicts, etc.)
  - Anything awaiting human approval (drafts, gated sends)
Keep it tight. Bullet points are fine."""


@dataclass
class AutonomousResult:
    """Full outcome of a Sentinel.run_autonomous() call."""
    directive: str
    summary: str                          # the model's final text turn
    tool_calls: list[dict]                # one entry per tool invocation
    findings: list[SentinelFinding]       # SentinelFindings the agent produced
    success: bool
    iterations: int
    duration_sec: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    stop_reason: str
    error: Optional[str] = None


def build_tools(sentinel_instance) -> tuple[list[SentinelFinding], list[AgentTool]]:
    """Build the AgentTool list wrapping Sentinel's Phase 0 kinds.

    Each tool's handler closes over `sentinel_instance` so it inherits
    the configured telemetry and (Phase 1+) calendar provider context.
    """
    findings: list[SentinelFinding] = []

    def _call(kind: str, payload: dict, context: Optional[dict] = None) -> dict:
        brief = SentinelBrief(
            kind=kind, payload=payload, context=context or {},
            requester="sentinel.autonomous",
        )
        finding = sentinel_instance.do(brief)
        findings.append(finding)
        return _summarize_finding(finding)

    return findings, [
        AgentTool(
            name="find_slot",
            description=(
                "Query a business's calendar for open windows in a date range. "
                "Returns {slots: [{start, end, staff_member}], n_slots}. Phase 0 "
                "stub returns not_implemented; Phase 1 wires to Google Calendar."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "business_id": {"type": "string"},
                    "window_start": {"type": "string", "description": "ISO datetime"},
                    "window_end": {"type": "string", "description": "ISO datetime"},
                    "duration_min": {"type": "integer"},
                    "staff_member": {"type": "string"},
                },
                "required": ["business_id", "window_start", "window_end", "duration_min"],
            },
            handler=lambda business_id, window_start, window_end, duration_min,
                          staff_member=None: _call(
                "find_slot",
                {"business_id": business_id, "window_start": window_start,
                 "window_end": window_end, "duration_min": duration_min,
                 "staff_member": staff_member},
            ),
        ),
        AgentTool(
            name="book_appointment",
            description=(
                "Write a confirmed appointment to the business's calendar. "
                "Returns {status: 'booked'|'conflict', calendar_event_id}. "
                "Always check_conflicts first when the time is user-proposed."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "business_id": {"type": "string"},
                    "start": {"type": "string", "description": "ISO datetime"},
                    "end": {"type": "string", "description": "ISO datetime"},
                    "title": {"type": "string"},
                    "attendee_email": {"type": "string"},
                    "attendee_name": {"type": "string"},
                    "staff_member": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["business_id", "start", "end", "title", "attendee_email"],
            },
            handler=lambda business_id, start, end, title, attendee_email,
                          attendee_name="", staff_member=None, notes="": _call(
                "book_appointment",
                {"business_id": business_id, "start": start, "end": end,
                 "title": title, "attendee_email": attendee_email,
                 "attendee_name": attendee_name, "staff_member": staff_member,
                 "notes": notes},
            ),
        ),
        AgentTool(
            name="reschedule",
            description=(
                "Move an existing calendar event to a new window. "
                "Returns {status: 'rescheduled'|'conflict'|'not_found'}."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "business_id": {"type": "string"},
                    "calendar_event_id": {"type": "string"},
                    "new_start": {"type": "string"},
                    "new_end": {"type": "string"},
                },
                "required": ["business_id", "calendar_event_id", "new_start", "new_end"],
            },
            handler=lambda business_id, calendar_event_id, new_start, new_end: _call(
                "reschedule",
                {"business_id": business_id, "calendar_event_id": calendar_event_id,
                 "new_start": new_start, "new_end": new_end},
            ),
        ),
        AgentTool(
            name="cancel",
            description=(
                "Cancel an existing calendar event. "
                "Returns {status: 'cancelled'|'not_found'}."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "business_id": {"type": "string"},
                    "calendar_event_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["business_id", "calendar_event_id"],
            },
            handler=lambda business_id, calendar_event_id, reason="": _call(
                "cancel",
                {"business_id": business_id, "calendar_event_id": calendar_event_id,
                 "reason": reason},
            ),
        ),
        AgentTool(
            name="check_conflicts",
            description=(
                "Cheap availability check on a single proposed window. "
                "Returns {status: 'clear'|'conflict', conflicts: [...]}. "
                "Use this BEFORE book_appointment when caller proposed a time."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "business_id": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "staff_member": {"type": "string"},
                },
                "required": ["business_id", "start", "end"],
            },
            handler=lambda business_id, start, end, staff_member=None: _call(
                "check_conflicts",
                {"business_id": business_id, "start": start, "end": end,
                 "staff_member": staff_member},
            ),
        ),
    ]


def _summarize_finding(finding: SentinelFinding) -> dict:
    """Trim a SentinelFinding to what the agent needs to see.

    Keep context tight across tool calls — pass status + reason + the
    high-value bits of payload, not full event blobs.
    """
    base = {"status": finding.status, "reason": finding.reason,
            "metadata": finding.metadata}
    kind = finding.kind
    p = finding.payload or {}

    if kind == "find_slot":
        slots = p.get("slots", [])
        return {**base, "n_slots": len(slots), "slots": slots[:10]}
    if kind == "book_appointment":
        return {**base, "calendar_event_id": p.get("calendar_event_id")}
    if kind in ("reschedule", "cancel"):
        return {**base, "calendar_event_id": p.get("calendar_event_id")}
    if kind == "check_conflicts":
        return {**base, "conflicts": p.get("conflicts", [])[:5]}
    return {**base, "payload": p}


def run_autonomous(
    sentinel_instance,
    directive: str,
    *,
    anthropic_api_key: str,
    model: str = "claude-sonnet-4-6",
    max_iterations: int = 10,
    progress_callback=None,
    should_cancel=None,
    max_cost_usd: Optional[float] = None,
) -> AutonomousResult:
    """Run Sentinel's agent loop on a natural-language directive.

    `sentinel_instance` should be a Sentinel() with telemetry and (Phase 1+)
    calendar provider injected — its kinds will be exposed to the agent.

    `max_cost_usd` aborts the loop before the next model call if cumulative
    estimated cost exceeds the cap. Useful for tenant-budgeted runs where
    a concierge directive should not exceed a few cents.
    """
    findings, tools = build_tools(sentinel_instance)

    result: AgentResult = run_agent_loop(
        system=SYSTEM_PROMPT,
        user_message=directive,
        tools=tools,
        api_key=anthropic_api_key,
        model=model,
        max_iterations=max_iterations,
        telemetry=sentinel_instance.telemetry,
        role="sentinel.autonomous",
        progress_callback=progress_callback,
        should_cancel=should_cancel,
        max_cost_usd=max_cost_usd,
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
        cost_usd=estimate_cost_usd(
            model, result.input_tokens, result.output_tokens,
            result.cache_write_tokens, result.cache_read_tokens,
        ),
        stop_reason=result.stop_reason,
        error=result.error,
    )


def _abbrev(result: Any) -> str:
    """Shorten a tool result for the AutonomousResult log."""
    import json
    s = json.dumps(result, default=str)
    return s if len(s) <= 300 else s[:297] + "..."
