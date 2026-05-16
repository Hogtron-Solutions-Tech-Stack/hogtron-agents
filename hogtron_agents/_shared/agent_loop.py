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
    input_tokens: int            # non-cached input tokens (billed at full input price)
    output_tokens: int
    cache_write_tokens: int      # tokens written to ephemeral cache (billed at 1.25× input)
    cache_read_tokens: int       # tokens read from ephemeral cache (billed at 0.10× input)
    duration_sec: float
    stop_reason: str             # "end_turn" | "max_iterations" | "error" | "cancelled" | "budget_exceeded"
    error: Optional[str] = None


# Per-million-tokens pricing for cost estimates. Update when Anthropic
# changes pricing. USD per million tokens.
#   input        — non-cached fresh input
#   output       — model output
#   cache_write  — first-time cache writes (1.25× input)
#   cache_read   — cache hits (0.10× input)
_PRICES_USD_PER_MTOK = {
    "claude-opus-4-7":           {"input": 15.00, "output": 75.00, "cache_write": 18.75, "cache_read": 1.50},
    "claude-sonnet-4-6":         {"input":  3.00, "output": 15.00, "cache_write":  3.75, "cache_read": 0.30},
    "claude-haiku-4-5-20251001": {"input":  1.00, "output":  5.00, "cache_write":  1.25, "cache_read": 0.10},
    "claude-haiku-4-5":          {"input":  1.00, "output":  5.00, "cache_write":  1.25, "cache_read": 0.10},
}


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """USD cost estimate. Defaults cache token args to 0 so callers that
    predate cache support still work.

    Unknown models log a warning and use Sonnet pricing — failing loud is
    better than silently over- or under-reporting at Opus rates."""
    p = _PRICES_USD_PER_MTOK.get(model)
    if p is None:
        import warnings
        warnings.warn(
            f"estimate_cost_usd: unknown model {model!r}; falling back to "
            "Sonnet 4.6 pricing. Update _PRICES_USD_PER_MTOK.",
            stacklevel=2,
        )
        p = _PRICES_USD_PER_MTOK["claude-sonnet-4-6"]
    return (
        input_tokens        * p["input"]
        + output_tokens     * p["output"]
        + cache_write_tokens * p["cache_write"]
        + cache_read_tokens  * p["cache_read"]
    ) / 1_000_000


def run_agent_loop(
    *,
    system: str,
    user_message: str,
    tools: list[AgentTool],
    api_key: str,
    model: str = "claude-sonnet-4-6",
    max_iterations: int = 10,
    max_tokens: int = 8000,
    thinking: bool = False,
    telemetry: Optional[TelemetrySink] = None,
    role: str = "agent",
    progress_callback: Optional[Callable[[dict], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    max_cost_usd: Optional[float] = None,
    tool_result_char_cap: int = 6000,
) -> AgentResult:
    """Run a Claude agent loop until end_turn or max_iterations.

    The loop is:
      1. Send user_message + tools to Claude
      2. If response has no tool_use blocks, return (end_turn)
      3. Else execute each tool, append tool_result blocks, loop

    Optional hooks (additive, backward-compatible):
      progress_callback({iteration, max_iterations, tool_calls_count,
                         last_tool, elapsed_sec})
        Invoked at the start of each iteration. UI updates live state from
        this. Exceptions in the callback are swallowed.
      should_cancel() -> bool
        Polled at the top of each iteration. When True, the loop returns
        early with stop_reason='cancelled' instead of making another model
        call. Useful for the Bridge's cancel button.
    """
    sink = telemetry or NullSink()
    client = anthropic.Anthropic(api_key=api_key)

    # Tools array is stable across iterations of a single run, so we cache it.
    # cache_control on the LAST tool tells Anthropic to cache everything up to
    # and including that block. ~5-10k tokens of tool schemas re-read at 10% of
    # input price on every subsequent iteration.
    tool_specs = [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]
    if tool_specs:
        tool_specs[-1]["cache_control"] = {"type": "ephemeral"}
    handlers = {t.name: t.handler for t in tools}

    # Initial user message gets cache_control so the conversation prefix stays
    # cached as the loop appends assistant+tool_result turns. Content must be a
    # block list for cache_control to attach.
    messages: list[dict] = [{"role": "user", "content": [
        {"type": "text", "text": user_message, "cache_control": {"type": "ephemeral"}},
    ]}]
    tool_calls_log: list[ToolCallLog] = []
    total_input = 0
    total_output = 0
    total_cache_write = 0
    total_cache_read = 0
    t_start = time.time()
    last_tool: Optional[str] = None

    for iteration in range(max_iterations):
        # Cooperative cancel check — fires before the next (expensive) model
        # call so a user clicking Cancel doesn't burn another iteration.
        if should_cancel and should_cancel():
            sink.log(role, f"cancelled at iter {iteration + 1}/{max_iterations}")
            return AgentResult(
                success=False,
                final_message="",
                tool_calls=tool_calls_log,
                iterations=iteration,
                input_tokens=total_input,
                output_tokens=total_output,
                cache_write_tokens=total_cache_write,
                cache_read_tokens=total_cache_read,
                duration_sec=time.time() - t_start,
                stop_reason="cancelled",
                error="cancelled by caller",
            )

        # Surface progress to any listener (Bridge UI poller, etc.).
        if progress_callback:
            try:
                progress_callback({
                    "iteration":        iteration + 1,
                    "max_iterations":   max_iterations,
                    "tool_calls_count": len(tool_calls_log),
                    "last_tool":        last_tool,
                    "elapsed_sec":      time.time() - t_start,
                })
            except Exception:  # noqa: BLE001
                pass

        # Budget guard: abort before making another (potentially expensive)
        # model call if estimated cost so far already exceeds the cap.
        if max_cost_usd is not None:
            current_cost = estimate_cost_usd(
                model, total_input, total_output,
                total_cache_write, total_cache_read,
            )
            if current_cost >= max_cost_usd:
                sink.log(role, f"budget exceeded: ${current_cost:.4f} >= "
                         f"${max_cost_usd:.4f} cap at iter {iteration + 1}", "warn")
                return AgentResult(
                    success=False,
                    final_message="",
                    tool_calls=tool_calls_log,
                    iterations=iteration,
                    input_tokens=total_input,
                    output_tokens=total_output,
                    cache_write_tokens=total_cache_write,
                    cache_read_tokens=total_cache_read,
                    duration_sec=time.time() - t_start,
                    stop_reason="budget_exceeded",
                    error=f"per-run budget ${max_cost_usd:.4f} hit at ${current_cost:.4f}",
                )

        sink.log(role, f"iter {iteration + 1}/{max_iterations}: model call")
        try:
            kwargs = {
                "model": model,
                "max_tokens": max_tokens,
                # System as a block list with cache_control caches the (stable)
                # system prompt across iterations + across runs within 5 min.
                "system": [
                    {"type": "text", "text": system,
                     "cache_control": {"type": "ephemeral"}},
                ],
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
                cache_write_tokens=total_cache_write,
                cache_read_tokens=total_cache_read,
                duration_sec=time.time() - t_start,
                stop_reason="error",
                error=f"Anthropic API error: {e}",
            )

        total_input  += resp.usage.input_tokens
        total_output += resp.usage.output_tokens
        # Cache token fields may be absent on older SDKs or non-cached calls.
        total_cache_write += getattr(resp.usage, "cache_creation_input_tokens", 0) or 0
        total_cache_read  += getattr(resp.usage, "cache_read_input_tokens", 0) or 0

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
                cache_write_tokens=total_cache_write,
                cache_read_tokens=total_cache_read,
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
            last_tool = block.name
            sink.log(role, f"  tool {block.name} -> "
                     f"{'error' if error else 'ok'} in {elapsed:.1f}s")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                # Cap per-result chars so a chatty tool can't blow up context
                # (and the replay cost on every subsequent iteration). 6000
                # chars ≈ 1500 tokens — enough for a real result, small enough
                # not to dominate the loop.
                "content": json.dumps(result, default=str)[:tool_result_char_cap],
            })

        # cache_control on the LAST tool_result extends the cached prefix to
        # the end of this turn, so the next iteration reads everything from
        # cache instead of re-billing it as fresh input.
        if tool_results:
            tool_results[-1]["cache_control"] = {"type": "ephemeral"}
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
        cache_write_tokens=total_cache_write,
        cache_read_tokens=total_cache_read,
        duration_sec=time.time() - t_start,
        stop_reason="max_iterations",
        error=f"agent did not converge in {max_iterations} iterations",
    )
