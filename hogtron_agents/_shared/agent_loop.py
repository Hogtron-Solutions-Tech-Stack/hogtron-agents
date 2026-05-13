"""Generic Claude agent loop — Layer 2 substrate.

Wraps anthropic.Anthropic().messages.create(tools=...) with the
tool_use -> tool_result loop. Used by each department's run_autonomous()
to chain Layer 1 calls in response to a natural-language directive.

Why not the claude-agent-sdk package?
  - Keeps deps minimal (just anthropic + pydantic, already required)
  - Loop is ~80 lines of transparent control flow
  - Easy to inject telemetry + cost tracking at each iteration
  - If we want SDK features later (built-in retries, structured streaming),
    swap this module out — callers don't change.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import anthropic

from .telemetry import TelemetrySink, NullSink


@dataclass
class AgentTool:
    """One callable exposed to the agent."""
    name: str
    description: str
    input_schema: dict  # JSONSchema-style; passed verbatim to Claude
    handler: Callable[..., Any]  # invoked with **block.input; return JSON-serializable


@dataclass
class ToolCallLog:
    """One tool invocation + its result (or error)."""
    tool: str
    input: dict
    result: Any
    elapsed_sec: float
    error: Optional[str] = None


@dataclass
class AgentResult:
    """Outcome of one full agent run."""
    success: bool
    final_message: str           # the model's last text turn
    tool_calls: list[ToolCallLog]
    iterations: int              # how many model turns happened
    input_tokens: int
    output_tokens: int
    duration_sec: float
    stop_reason: str             # "end_turn" | "max_iterations" | "error"
    error: Optional[str] = None


# Per-million-tokens pricing for cost estimates. Update when Anthropic
# changes pricing. These are USD per million tokens.
_PRICES_USD_PER_MTOK = {
    "claude-opus-4-7":           {"input": 15.00, "output": 75.00},
    "claude-haiku-4-5-20251001": {"input": 1.00,  "output": 5.00},
    # Fallback for unknown models — same as Opus 4.7 (overestimates rather than under)
    "_default":                  {"input": 15.00, "output": 75.00},
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    p = _PRICES_USD_PER_MTOK.get(model) or _PRICES_USD_PER_MTOK["_default"]
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000


def run_agent_loop(
    *,
    system: str,
    user_message: str,
    tools: list[AgentTool],
    api_key: str,
    model: str = "claude-opus-4-7",
    max_iterations: int = 10,
    max_tokens: int = 8000,
    thinking: bool = True,
    telemetry: Optional[TelemetrySink] = None,
    role: str = "agent",
) -> AgentResult:
    """Run a Claude agent loop until end_turn or max_iterations.

    The loop is:
      1. Send user_message + tools to Claude
      2. If response has no tool_use blocks, return (end_turn)
      3. Else execute each tool, append tool_result blocks, loop
    """
    sink = telemetry or NullSink()
    client = anthropic.Anthropic(api_key=api_key)

    tool_specs = [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]
    handlers = {t.name: t.handler for t in tools}

    messages: list[dict] = [{"role": "user", "content": user_message}]
    tool_calls_log: list[ToolCallLog] = []
    total_input = 0
    total_output = 0
    t_start = time.time()

    for iteration in range(max_iterations):
        sink.log(role, f"iter {iteration + 1}/{max_iterations}: model call")
        try:
            kwargs = {
                "model": model,
                "max_tokens": max_tokens,
                "system": system,
                "tools": tool_specs,
                "messages": messages,
            }
            if thinking:
                kwargs["thinking"] = {"type": "adaptive"}
            resp = client.messages.create(**kwargs)
        except anthropic.APIError as e:
            return AgentResult(
                success=False,
                final_message="",
                tool_calls=tool_calls_log,
                iterations=iteration,
                input_tokens=total_input,
                output_tokens=total_output,
                duration_sec=time.time() - t_start,
                stop_reason="error",
                error=f"Anthropic API error: {e}",
            )

        total_input += resp.usage.input_tokens
        total_output += resp.usage.output_tokens

        if resp.stop_reason == "end_turn":
            final_text = "".join(b.text for b in resp.content if b.type == "text")
            sink.log(role, f"end_turn after {iteration + 1} iter(s), "
                     f"{len(tool_calls_log)} tool call(s)")
            return AgentResult(
                success=True,
                final_message=final_text,
                tool_calls=tool_calls_log,
                iterations=iteration + 1,
                input_tokens=total_input,
                output_tokens=total_output,
                duration_sec=time.time() - t_start,
                stop_reason="end_turn",
            )

        # The model emitted tool_use blocks. Append the assistant turn and
        # execute each tool, building the matching tool_result blocks.
        messages.append({"role": "assistant", "content": resp.content})
        tool_results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            handler = handlers.get(block.name)
            t_tool = time.time()
            error = None
            if handler is None:
                result = {"error": f"unknown tool: {block.name!r}"}
                error = result["error"]
            else:
                try:
                    result = handler(**block.input)
                except Exception as e:
                    result = {"error": str(e)[:500]}
                    error = result["error"]
            elapsed = time.time() - t_tool

            tool_calls_log.append(ToolCallLog(
                tool=block.name, input=dict(block.input),
                result=result, elapsed_sec=elapsed, error=error,
            ))
            sink.log(role, f"  tool {block.name} -> "
                     f"{'error' if error else 'ok'} in {elapsed:.1f}s")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, default=str)[:25000],  # cap to avoid context blowup
            })

        messages.append({"role": "user", "content": tool_results})

    # max_iterations exhausted without end_turn
    sink.log(role, f"max_iterations ({max_iterations}) exhausted", "warn")
    return AgentResult(
        success=False,
        final_message="",
        tool_calls=tool_calls_log,
        iterations=max_iterations,
        input_tokens=total_input,
        output_tokens=total_output,
        duration_sec=time.time() - t_start,
        stop_reason="max_iterations",
        error=f"agent did not converge in {max_iterations} iterations",
    )
