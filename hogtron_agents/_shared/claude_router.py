"""Claude routing layer — API-canonical with opportunistic Max subscription.

Two entrypoints matching the existing call shapes:
  - route_messages_create(...) — for tool-dispatch loops (agent_loop.py)
  - route_messages_parse(...)  — for structured output (.parse() sites)

Backend selection (API-canonical per Sean's approved plan):
  1. Default: anthropic.Anthropic(api_key=...).messages.create / .parse
  2. If HOGTRON_TRY_MAX=true AND quota_gate green AND credentials exist:
     try Max first via claude-agent-sdk, fall back to API on any failure.
  3. If HOGTRON_FORCE_BACKEND=api: API only, never try Max
     (FactoryHQ on Railway, CI, anything containerized).

Every call writes one JSONL line to:
    %LOCALAPPDATA%\\HogTron\\logs\\router-yyyyMMdd.jsonl

Dry-run mode (HOGTRON_DRY_RUN=true): logs what would happen and returns a
stub response. No external API calls, no side effects.

This module is intentionally SYNCHRONOUS — existing call sites are sync.
The Max path uses asyncio.run() internally to drive claude-agent-sdk.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional, Type, Union

import anthropic
import requests
from pydantic import BaseModel, ValidationError

from . import quota_gate
from . import provider_breaker


# ---------------------------------------------------------------------------
# Pricing — duplicated from agent_loop.py to avoid circular import.
# Keep in sync if the canonical table there is updated.
# ---------------------------------------------------------------------------

_PRICES_USD_PER_MTOK = {
    "claude-opus-4-7":           {"input": 15.00, "output": 75.00, "cache_write": 18.75, "cache_read": 1.50},
    "claude-sonnet-4-6":         {"input":  3.00, "output": 15.00, "cache_write":  3.75, "cache_read": 0.30},
    "claude-sonnet-4-5":         {"input":  3.00, "output": 15.00, "cache_write":  3.75, "cache_read": 0.30},
    "claude-haiku-4-5-20251001": {"input":  1.00, "output":  5.00, "cache_write":  1.25, "cache_read": 0.10},
    "claude-haiku-4-5":          {"input":  1.00, "output":  5.00, "cache_write":  1.25, "cache_read": 0.10},
}


def _estimate_cost_usd(model: str, usage: dict) -> float:
    p = _PRICES_USD_PER_MTOK.get(model) or _PRICES_USD_PER_MTOK["claude-sonnet-4-6"]
    inp = usage.get("input_tokens", 0) or 0
    out = usage.get("output_tokens", 0) or 0
    cw = usage.get("cache_creation_input_tokens", 0) or 0
    cr = usage.get("cache_read_input_tokens", 0) or 0
    return (inp * p["input"] + out * p["output"]
            + cw * p["cache_write"] + cr * p["cache_read"]) / 1_000_000


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------

@dataclass
class RouterResponse:
    """Normalized response across backends.

    `content` mirrors the anthropic SDK shape (list of typed blocks). For Max
    path responses translated from claude-agent-sdk, we synthesize anthropic-
    compatible block dicts with `type` and `text` keys so the existing
    iteration logic in agent_loop.py continues to work without changes."""
    content: list                       # anthropic-shaped content blocks
    text: str                           # convenience: concatenated text content
    stop_reason: str                    # "end_turn" | "max_tokens" | "tool_use" | ...
    usage: dict                         # input/output/cache_creation/cache_read tokens
    parsed_output: Any = None           # only populated for .parse() — the Pydantic instance
    backend: str = "api"                # "api" | "max" | "local"
    used_subscription: bool = False
    fallback_reason: Optional[str] = None
    elapsed_sec: float = 0.0
    retries: int = 0
    schema_failures: int = 0            # only meaningful for .parse() on Max
    estimated_api_cost_usd: float = 0.0
    model: str = ""
    dry_run: bool = False


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

def _log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "HogTron" / "logs"
    return Path.home() / ".HogTron" / "logs"


def _emit_telemetry(agent: str, response: RouterResponse) -> None:
    """Append one JSONL line per call. Best-effort — never raises."""
    try:
        log_dir = _log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / f"router-{datetime.now().strftime('%Y%m%d')}.jsonl"
        line = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "model": response.model,
            "backend": response.backend,
            "used_subscription": response.used_subscription,
            "fallback_reason": response.fallback_reason,
            "input_tokens": response.usage.get("input_tokens", 0),
            "output_tokens": response.usage.get("output_tokens", 0),
            "cache_creation_tokens": response.usage.get("cache_creation_input_tokens", 0),
            "cache_read_tokens": response.usage.get("cache_read_input_tokens", 0),
            "elapsed_sec": round(response.elapsed_sec, 3),
            "retries": response.retries,
            "schema_failures": response.schema_failures,
            "estimated_api_cost_usd": round(response.estimated_api_cost_usd, 6),
            "stop_reason": response.stop_reason,
            "dry_run": response.dry_run,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
    except Exception:
        # Telemetry must never break the call. Print to stderr for debugging
        # but don't propagate.
        import sys
        print(f"[claude_router] telemetry write failed: {traceback.format_exc()}",
              file=sys.stderr)


# ---------------------------------------------------------------------------
# Credential check
# ---------------------------------------------------------------------------

def _credentials_path() -> Path:
    return Path.home() / ".claude" / ".credentials.json"


def _credentials_present() -> bool:
    return _credentials_path().exists() and _credentials_path().stat().st_size > 0


# ---------------------------------------------------------------------------
# Dry-run shortcut
# ---------------------------------------------------------------------------

def _is_dry_run() -> bool:
    return os.environ.get("HOGTRON_DRY_RUN", "").strip().lower() == "true"


def _force_backend() -> str:
    return (
        os.environ.get("HOGTRON_FORCE_BACKEND")
        or os.environ.get("HOGTRON_LLM_BACKEND")
        or ""
    ).strip().lower()


def _local_base_url() -> str:
    return os.environ.get("LOCAL_LLM_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/")


def _local_model(fallback: str) -> str:
    return os.environ.get("LOCAL_LLM_MODEL") or fallback


def _local_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    key = os.environ.get("LOCAL_LLM_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _local_timeout() -> int:
    try:
        return int(os.environ.get("LOCAL_LLM_TIMEOUT_SECONDS", "180") or 180)
    except ValueError:
        return 180


def _local_retries() -> int:
    try:
        return max(1, int(os.environ.get("LOCAL_LLM_RETRIES", "1") or 1))
    except ValueError:
        return 1


def _local_use_json_schema() -> bool:
    return os.environ.get("LOCAL_LLM_USE_JSON_SCHEMA", "false").strip().lower() in ("1", "true", "yes")


def using_local_backend() -> bool:
    return _force_backend() == "local"


@dataclass
class _OpenAICompatProvider:
    """An OpenAI-compatible chat endpoint. Drives both the local Ollama backend
    and the cloud fallback providers (xAI, Gemini) — they all speak the same
    /chat/completions shape, so the anthropic<->openai translation below is
    written once and reused."""
    name: str
    base_url: str
    model: str
    api_key: str = ""
    timeout: int = 180
    retries: int = 1
    use_json_schema: bool = False


def _local_provider(model_fallback: str) -> _OpenAICompatProvider:
    return _OpenAICompatProvider(
        name="local",
        base_url=_local_base_url(),
        model=_local_model(model_fallback),
        api_key=os.environ.get("LOCAL_LLM_API_KEY", ""),
        timeout=_local_timeout(),
        retries=_local_retries(),
        use_json_schema=_local_use_json_schema(),
    )


# ---------------------------------------------------------------------------
# Cloud fallback providers (xAI, Gemini) — used when the Anthropic API path
# fails because credits are exhausted (or it's rate-limited / 5xx / down).
# Both speak the OpenAI-compatible chat API, so they ride the same translation
# layer as the local backend. Order is env-tunable; default mirrors the audit
# tools (Anthropic -> Gemini -> Grok).
# ---------------------------------------------------------------------------

_FALLBACK_SPECS = {
    "gemini": {
        "base_url":      "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env":       "GEMINI_API_KEY",
        "model_env":     "GEMINI_MODEL",
        "model_default": "gemini-2.5-flash",
    },
    "xai": {
        "base_url":      "https://api.x.ai/v1",
        "key_env":       "XAI_API_KEY",
        "model_env":     "XAI_MODEL",
        "model_default": "grok-4-fast-non-reasoning",
    },
}


def _fallback_order() -> list[str]:
    raw = os.environ.get("HOGTRON_FALLBACK_PROVIDERS", "gemini,xai")
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def _fallback_providers() -> list[_OpenAICompatProvider]:
    """Ordered, key-present cloud providers to try after Anthropic. Empty when
    no fallback keys are configured — in which case the router behaves exactly
    as before (Anthropic-only)."""
    out: list[_OpenAICompatProvider] = []
    for name in _fallback_order():
        spec = _FALLBACK_SPECS.get(name)
        if not spec:
            continue
        key = os.environ.get(spec["key_env"], "")
        if not key:
            continue
        out.append(_OpenAICompatProvider(
            name=name,
            base_url=spec["base_url"],
            model=os.environ.get(spec["model_env"]) or spec["model_default"],
            api_key=key,
            timeout=_local_timeout(),
            retries=1,
        ))
    return out


def _is_credit_exhaustion(exc: Exception) -> bool:
    """Anthropic returns HTTP 400 with a 'credit balance is too low' message
    when the account is out of credits — distinct from a malformed-request 400."""
    msg = str(exc).lower()
    return "credit balance" in msg or "billing" in msg or "plans & billing" in msg


def _should_fallback(exc: Exception) -> bool:
    """Is this Anthropic failure recoverable by trying another provider?

    Yes for credit exhaustion, rate limits, server errors, and connection
    problems. No for bad API keys or malformed requests — those fail the same
    way everywhere (or are our own bug), so falling back just hides them."""
    if isinstance(exc, (anthropic.AuthenticationError,
                        anthropic.PermissionDeniedError,
                        anthropic.NotFoundError)):
        return False
    if isinstance(exc, anthropic.BadRequestError):
        return _is_credit_exhaustion(exc)
    if isinstance(exc, (anthropic.RateLimitError,
                        anthropic.InternalServerError,
                        anthropic.APIConnectionError,
                        anthropic.APITimeoutError)):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return getattr(exc, "status_code", 0) >= 500
    return False


def llm_available(api_key: Optional[str] = None) -> bool:
    if using_local_backend():
        return bool(_local_base_url() and _local_model(""))
    return bool(api_key or os.environ.get("ANTHROPIC_API_KEY"))


def _dry_run_response(*, model: str, parsed: bool, output_format: Optional[Type[BaseModel]]) -> RouterResponse:
    """Stub response for dry-run. No LLM call, no side effects."""
    stub_text = "[DRY_RUN] no LLM call made"
    parsed_output = None
    if parsed and output_format is not None:
        # Build a minimal valid instance if the schema allows; else None
        try:
            # Attempt construct() to skip validation — gives caller a non-None
            # of the right type for downstream code to inspect.
            parsed_output = output_format.model_construct()
        except Exception:
            parsed_output = None
    return RouterResponse(
        content=[{"type": "text", "text": stub_text}],
        text=stub_text,
        stop_reason="end_turn",
        usage={"input_tokens": 0, "output_tokens": 0,
               "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        parsed_output=parsed_output,
        backend="dry_run",
        used_subscription=False,
        fallback_reason="dry_run",
        elapsed_sec=0.0,
        retries=0,
        schema_failures=0,
        estimated_api_cost_usd=0.0,
        model=model,
        dry_run=True,
    )


# ---------------------------------------------------------------------------
# API backend (canonical)
# ---------------------------------------------------------------------------

def _api_create(*, model: str, max_tokens: int, system: Any, messages: list,
                tools: Optional[list], thinking: Optional[dict],
                api_key: Optional[str]) -> dict:
    """Call anthropic SDK messages.create. Returns normalized dict."""
    client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    if tools is not None:
        kwargs["tools"] = tools
    if thinking is not None:
        kwargs["thinking"] = thinking
    resp = client.messages.create(**kwargs)
    return {
        "content": list(resp.content),
        "stop_reason": resp.stop_reason or "end_turn",
        "usage": {
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
            "cache_creation_input_tokens": getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        },
    }


def _api_parse(*, model: str, max_tokens: int, system: str, messages: list,
               output_format: Type[BaseModel], api_key: Optional[str]) -> dict:
    """Call anthropic SDK messages.parse with structured output."""
    client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    resp = client.messages.parse(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        output_format=output_format,
    )
    text_parts = []
    for b in resp.content:
        if getattr(b, "type", None) == "text":
            text_parts.append(b.text)
    return {
        "content": list(resp.content),
        "text": "".join(text_parts),
        "stop_reason": resp.stop_reason or "end_turn",
        "usage": {
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
            "cache_creation_input_tokens": getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        },
        "parsed_output": resp.parsed_output,
    }


# ---------------------------------------------------------------------------
# Local backend (OpenAI-compatible; no Anthropic API usage)
# ---------------------------------------------------------------------------

def _system_to_text(system: Any) -> str:
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        return "\n".join(
            (b.get("text") if isinstance(b, dict) else getattr(b, "text", "")) or ""
            for b in system
            if (isinstance(b, dict) and b.get("type") == "text")
            or getattr(b, "type", None) == "text"
        )
    return str(system or "")


def _anthropic_messages_to_openai(messages: list) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        if not isinstance(content, list):
            out.append({"role": role, "content": str(content)})
            continue

        text_parts: list[str] = []
        tool_calls: list[dict] = []
        tool_results: list[dict] = []
        for block in content:
            btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
            if btype == "text":
                text_parts.append((block.get("text") if isinstance(block, dict) else getattr(block, "text", "")) or "")
            elif btype == "tool_use":
                name = block.get("name") if isinstance(block, dict) else getattr(block, "name", "")
                raw_input = block.get("input") if isinstance(block, dict) else getattr(block, "input", {})
                tool_id = block.get("id") if isinstance(block, dict) else getattr(block, "id", f"call_{len(tool_calls)}")
                tool_calls.append({
                    "id": tool_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(raw_input or {}, default=str),
                    },
                })
            elif btype == "tool_result":
                tool_id = block.get("tool_use_id") if isinstance(block, dict) else getattr(block, "tool_use_id", "")
                result_content = block.get("content") if isinstance(block, dict) else getattr(block, "content", "")
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": result_content if isinstance(result_content, str) else json.dumps(result_content, default=str),
                })

        if tool_results:
            out.extend(tool_results)
            continue

        msg: dict[str, Any] = {"role": role, "content": "\n".join(text_parts) if text_parts else None}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        out.append(msg)
    return out


def _tools_to_openai(tools: Optional[list]) -> Optional[list]:
    if not tools:
        return None
    converted = []
    for tool in tools:
        converted.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return converted


def _openai_post(provider: _OpenAICompatProvider, payload: dict) -> dict:
    url = f"{provider.base_url.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if provider.api_key:
        headers["Authorization"] = f"Bearer {provider.api_key}"
    retries = max(1, provider.retries)
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=provider.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(2)
    raise RuntimeError(f"{provider.name} LLM request failed: {last_error}") from last_error


def _local_usage(data: dict) -> dict:
    usage = data.get("usage") or {}
    return {
        "input_tokens": usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0) or 0,
        "output_tokens": usage.get("completion_tokens", 0) or usage.get("output_tokens", 0) or 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }


def _local_create(*, model: str, max_tokens: int, system: Any, messages: list,
                  tools: Optional[list], thinking: Optional[dict]) -> dict:
    return _openai_create(_local_provider(model), max_tokens=max_tokens, system=system,
                          messages=messages, tools=tools, thinking=thinking)


def _openai_create(provider: _OpenAICompatProvider, *, max_tokens: int, system: Any,
                   messages: list, tools: Optional[list], thinking: Optional[dict]) -> dict:
    local_messages = [{"role": "system", "content": _system_to_text(system)}]
    local_messages.extend(_anthropic_messages_to_openai(messages))
    payload: dict[str, Any] = {
        "model": provider.model,
        "messages": local_messages,
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    openai_tools = _tools_to_openai(tools)
    if openai_tools:
        payload["tools"] = openai_tools
        payload["tool_choice"] = "auto"

    data = _openai_post(provider, payload)
    msg = data["choices"][0]["message"]
    content = []
    if msg.get("content"):
        content.append(SimpleNamespace(type="text", text=msg["content"]))
    for i, call in enumerate(msg.get("tool_calls") or []):
        fn = call.get("function") or {}
        args_raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(args_raw)
        except json.JSONDecodeError:
            args = {}
        content.append(SimpleNamespace(
            type="tool_use",
            id=call.get("id") or f"call_{i}",
            name=fn.get("name", ""),
            input=args,
        ))
    stop_reason = "tool_use" if any(getattr(b, "type", None) == "tool_use" for b in content) else "end_turn"
    return {
        "content": content,
        "stop_reason": stop_reason,
        "usage": _local_usage(data),
    }


def _local_parse(*, model: str, max_tokens: int, system: str, messages: list,
                 output_format: Type[BaseModel]) -> dict:
    return _openai_parse(_local_provider(model), max_tokens=max_tokens, system=system,
                         messages=messages, output_format=output_format)


def _openai_parse(provider: _OpenAICompatProvider, *, max_tokens: int, system: str,
                  messages: list, output_format: Type[BaseModel]) -> dict:
    schema_json = json.dumps(output_format.model_json_schema(), indent=2)
    local_system = (
        f"{system}\n\n"
        "Respond with ONLY raw JSON matching this JSON Schema. "
        "No markdown, no prose, no code fences.\n"
        f"{schema_json}"
    )
    local_messages = [{"role": "system", "content": local_system}]
    local_messages.extend(_anthropic_messages_to_openai(messages))
    payload: dict[str, Any] = {
        "model": provider.model,
        "messages": local_messages,
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    if provider.use_json_schema:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "hogtron_output", "schema": output_format.model_json_schema(), "strict": True},
        }

    schema_failures = 0
    last_text = ""
    last_usage = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    for attempt in range(2):
        data = _openai_post(provider, payload)
        last_usage = _local_usage(data)
        last_text = data["choices"][0]["message"].get("content") or ""
        json_str = _extract_json(last_text)
        if not json_str:
            schema_failures += 1
        else:
            try:
                parsed = output_format.model_validate_json(json_str)
                return {
                    "content": [SimpleNamespace(type="text", text=last_text)],
                    "text": last_text,
                    "stop_reason": "end_turn",
                    "usage": last_usage,
                    "parsed_output": parsed,
                    "schema_failures": schema_failures,
                }
            except ValidationError:
                schema_failures += 1
        payload["messages"].append({"role": "user", "content": "Your last response did not match the schema. Reply again with only valid raw JSON."})

    raise RuntimeError(f"{provider.name} LLM schema validation failed twice. Last response: {last_text[:300]!r}")


# ---------------------------------------------------------------------------
# Max backend (opportunistic, claude-agent-sdk)
# ---------------------------------------------------------------------------

# Lazy import — only loaded when HOGTRON_TRY_MAX=true and we actually attempt
# the Max path. Keeps the dependency optional for environments that never
# want to touch the SDK (Railway, CI).
_sdk = None


def _lazy_sdk():
    global _sdk
    if _sdk is None:
        import claude_agent_sdk as _mod
        _sdk = _mod
    return _sdk


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def _extract_json(text: str) -> Optional[str]:
    """Pull a JSON object out of model output that might be wrapped in
    fences or prose. Returns the JSON string, or None if nothing parseable."""
    # First try: whole text is already JSON
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return stripped
    # Second try: ```json fence
    m = _JSON_BLOCK_RE.search(text)
    if m:
        return m.group(1)
    # Third try: greedy braces match
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last > first:
        return text[first:last + 1]
    return None


async def _max_query_text(*, system: str, user_prompt: str, model: str,
                          max_tokens: int) -> tuple[str, dict, str]:
    """Run one Max query, return (text, usage_dict, stop_reason).

    Raises on any SDK error — caller catches and triggers fallback."""
    sdk = _lazy_sdk()
    opts = sdk.ClaudeAgentOptions(
        system_prompt=system,
        tools=[],            # one-shot, no tools
        max_turns=1,
        model=model,
    )
    text_parts: list[str] = []
    result_msg = None
    async for msg in sdk.query(prompt=user_prompt, options=opts):
        if isinstance(msg, sdk.AssistantMessage):
            for b in msg.content:
                if isinstance(b, sdk.TextBlock):
                    text_parts.append(b.text)
        elif isinstance(msg, sdk.ResultMessage):
            result_msg = msg
        elif isinstance(msg, sdk.RateLimitEvent):
            # Surface this distinctly so caller can trip the quota gate
            raise _QuotaExhausted(getattr(msg, "retry_after_seconds", None))

    text = "".join(text_parts)
    usage = {}
    stop_reason = "end_turn"
    if result_msg is not None:
        if getattr(result_msg, "is_error", False):
            raise RuntimeError(f"Max SDK reported error: {getattr(result_msg, 'subtype', 'unknown')}")
        ru = getattr(result_msg, "usage", None) or {}
        usage = {
            "input_tokens": ru.get("input_tokens", 0),
            "output_tokens": ru.get("output_tokens", 0),
            "cache_creation_input_tokens": ru.get("cache_creation_input_tokens", 0),
            "cache_read_input_tokens": ru.get("cache_read_input_tokens", 0),
        }
    return text, usage, stop_reason


class _QuotaExhausted(Exception):
    """Internal marker — SDK rate limit hit. Triggers cooldown + fallback."""
    def __init__(self, retry_after_sec: Optional[int] = None):
        self.retry_after_sec = retry_after_sec
        super().__init__(f"Max quota exhausted; retry_after={retry_after_sec}")


def _classify_max_error(exc: Exception) -> tuple[str, bool]:
    """Returns (fallback_reason, is_credential_failure)."""
    msg = str(exc).lower()
    if isinstance(exc, _QuotaExhausted):
        return ("quota_exhausted", False)
    sdk_mod = _sdk  # may be None if lazy import never happened
    if sdk_mod is not None:
        if isinstance(exc, sdk_mod.CLINotFoundError):
            return ("claude_cli_missing", True)
        if isinstance(exc, sdk_mod.CLIConnectionError):
            return ("cli_connection_error", False)
        if isinstance(exc, sdk_mod.ProcessError):
            return ("sdk_process_error", False)
        if isinstance(exc, sdk_mod.CLIJSONDecodeError):
            return ("sdk_json_decode_error", False)
    if "credentials" in msg or "auth" in msg or "401" in msg or "403" in msg:
        return ("credentials_invalid", True)
    if "429" in msg or "rate" in msg or "quota" in msg or "limit" in msg:
        return ("quota_exhausted", False)
    return (f"max_error:{type(exc).__name__}", False)


# ---------------------------------------------------------------------------
# Public entrypoint: route_messages_parse
# ---------------------------------------------------------------------------

def route_messages_parse(
    *,
    agent: str,
    model: str,
    system: str,
    messages: list,
    output_format: Type[BaseModel],
    max_tokens: int = 4000,
    api_key: Optional[str] = None,
) -> RouterResponse:
    """Drop-in replacement for `anthropic.Anthropic().messages.parse(...)`.

    Returns a RouterResponse whose `parsed_output` field is the validated
    Pydantic instance — same shape as anthropic SDK's resp.parsed_output.

    Backend selection: see module docstring."""
    if _is_dry_run():
        resp = _dry_run_response(model=model, parsed=True, output_format=output_format)
        _emit_telemetry(agent, resp)
        return resp

    t_start = time.time()
    if _force_backend() == "local":
        raw = _local_parse(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            output_format=output_format,
        )
        response = RouterResponse(
            content=raw["content"],
            text=raw["text"],
            stop_reason=raw["stop_reason"],
            usage=raw["usage"],
            parsed_output=raw["parsed_output"],
            backend="local",
            used_subscription=False,
            fallback_reason=None,
            elapsed_sec=time.time() - t_start,
            retries=0,
            schema_failures=raw.get("schema_failures", 0),
            estimated_api_cost_usd=0.0,
            model=_local_model(model),
        )
        _emit_telemetry(agent, response)
        return response

    if quota_gate.should_try_subscription() and _credentials_present():
        try:
            return _do_parse_via_max(
                agent=agent, model=model, system=system, messages=messages,
                output_format=output_format, max_tokens=max_tokens, api_key=api_key,
                t_start=t_start,
            )
        except Exception as e:
            reason, is_cred = _classify_max_error(e)
            if reason == "quota_exhausted":
                retry_sec = getattr(e, "retry_after_sec", None)
                quota_gate.record_quota_exhausted(retry_sec)
            elif is_cred:
                quota_gate.record_credential_failure()
            else:
                quota_gate.record_call(used_subscription=True, failed=True)
            # Fall through to API
            return _do_parse_via_api(
                agent=agent, model=model, system=system, messages=messages,
                output_format=output_format, max_tokens=max_tokens, api_key=api_key,
                t_start=t_start, fallback_reason=reason,
            )

    # API canonical path
    return _do_parse_via_api(
        agent=agent, model=model, system=system, messages=messages,
        output_format=output_format, max_tokens=max_tokens, api_key=api_key,
        t_start=t_start, fallback_reason=None,
    )


def _parse_response(*, agent: str, model: str, raw: dict, t_start: float,
                    fallback_reason: Optional[str], backend: str, cost: float) -> RouterResponse:
    response = RouterResponse(
        content=raw["content"],
        text=raw.get("text", ""),
        stop_reason=raw["stop_reason"],
        usage=raw["usage"],
        parsed_output=raw.get("parsed_output"),
        backend=backend,
        used_subscription=False,
        fallback_reason=fallback_reason,
        elapsed_sec=time.time() - t_start,
        retries=0,
        schema_failures=raw.get("schema_failures", 0),
        estimated_api_cost_usd=cost,
        model=model,
    )
    _emit_telemetry(agent, response)
    return response


def _do_parse_via_api(*, agent: str, model: str, system: str, messages: list,
                      output_format: Type[BaseModel], max_tokens: int,
                      api_key: Optional[str], t_start: float,
                      fallback_reason: Optional[str]) -> RouterResponse:
    providers = _fallback_providers()
    skip_anthropic = bool(providers) and provider_breaker.anthropic_in_cooldown()
    anthropic_exc: Optional[Exception] = None

    if skip_anthropic:
        fallback_reason = fallback_reason or "anthropic_cooldown"
    else:
        try:
            raw = _api_parse(model=model, max_tokens=max_tokens, system=system,
                             messages=messages, output_format=output_format, api_key=api_key)
            provider_breaker.clear_anthropic_cooldown()
            return _parse_response(agent=agent, model=model, raw=raw, t_start=t_start,
                                   fallback_reason=fallback_reason, backend="api",
                                   cost=_estimate_cost_usd(model, raw["usage"]))
        except Exception as e:
            if not (providers and _should_fallback(e)):
                raise
            anthropic_exc = e
            if _is_credit_exhaustion(e):
                provider_breaker.record_anthropic_exhausted(str(e)[:200])
            fallback_reason = "anthropic_credit_exhausted" if _is_credit_exhaustion(e) else "anthropic_unavailable"

    errors = []
    for provider in providers:
        try:
            raw = _openai_parse(provider, max_tokens=max_tokens, system=system,
                                messages=messages, output_format=output_format)
            return _parse_response(agent=agent, model=provider.model, raw=raw, t_start=t_start,
                                   fallback_reason=fallback_reason, backend=provider.name, cost=0.0)
        except Exception as e:
            errors.append(f"{provider.name}: {e}")

    if anthropic_exc is not None:
        raise anthropic_exc
    raise RuntimeError("All LLM providers failed — " + " | ".join(errors))


def _do_parse_via_max(*, agent: str, model: str, system: str, messages: list,
                      output_format: Type[BaseModel], max_tokens: int,
                      api_key: Optional[str], t_start: float) -> RouterResponse:
    """Try Max with schema-as-prompt. Up to one retry on schema failure.
    Two failures = raise so caller falls back to API path (no cooldown trip)."""

    # Compose system prompt with schema injection
    schema_json = json.dumps(output_format.model_json_schema(), indent=2)
    augmented_system = (
        f"{system}\n\n"
        f"<output_format>\n"
        f"You MUST respond with ONLY a JSON object matching this schema. "
        f"No prose, no explanation, no markdown fences — just raw JSON.\n"
        f"<schema>\n{schema_json}\n</schema>\n"
        f"</output_format>"
    )

    user_prompt = _flatten_user_messages(messages)
    schema_failures = 0
    last_text = ""
    last_usage: dict = {}
    last_stop = "end_turn"

    for attempt in range(2):  # initial + one retry
        prompt = user_prompt if attempt == 0 else (
            user_prompt + "\n\nYour previous reply did not parse against the schema. "
            "Respond again with ONLY the raw JSON object."
        )
        text, usage, stop = asyncio.run(_max_query_text(
            system=augmented_system, user_prompt=prompt, model=model, max_tokens=max_tokens,
        ))
        last_text, last_usage, last_stop = text, usage, stop

        json_str = _extract_json(text)
        if json_str is None:
            schema_failures += 1
            continue

        try:
            parsed = output_format.model_validate_json(json_str)
        except ValidationError:
            schema_failures += 1
            continue

        # Success
        quota_gate.record_call(used_subscription=True, failed=False)
        response = RouterResponse(
            content=[{"type": "text", "text": text}],
            text=text,
            stop_reason=stop,
            usage=usage,
            parsed_output=parsed,
            backend="max",
            used_subscription=True,
            fallback_reason=None,
            elapsed_sec=time.time() - t_start,
            retries=attempt,
            schema_failures=schema_failures,
            estimated_api_cost_usd=_estimate_cost_usd(model, usage),
            model=model,
        )
        _emit_telemetry(agent, response)
        return response

    # Two consecutive schema failures — record then raise so caller falls back.
    # We did consume Max quota for these attempts.
    quota_gate.record_call(used_subscription=True, failed=True)
    raise RuntimeError(
        f"Max schema-validation failed twice on agent={agent}; "
        f"falling back to API. Last response: {last_text[:200]!r}"
    )


def _flatten_user_messages(messages: list) -> str:
    """Convert anthropic messages list to a single string for SDK query."""
    parts = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = "\n".join(
                b.get("text", "") if isinstance(b, dict) else getattr(b, "text", "")
                for b in content
                if (isinstance(b, dict) and b.get("type") == "text")
                or getattr(b, "type", None) == "text"
            )
        else:
            text = str(content)
        if role != "user":
            parts.append(f"[{role}]\n{text}")
        else:
            parts.append(text)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Public entrypoint: route_messages_create
# ---------------------------------------------------------------------------

def route_messages_create(
    *,
    agent: str,
    model: str,
    system: Any,
    messages: list,
    tools: Optional[list] = None,
    thinking: Optional[dict] = None,
    max_tokens: int = 8000,
    api_key: Optional[str] = None,
) -> RouterResponse:
    """Drop-in replacement for `anthropic.Anthropic().messages.create(...)`.

    For Phase 0 this routes API-only — Max tool-loop translation is Phase 2
    (conditional). The router exists now so agent_loop.py can be swapped
    over without code churn when/if Phase 2 ships.

    Returns RouterResponse with anthropic-shaped `content` blocks so the
    existing iteration logic in agent_loop.py:282 works unchanged."""
    if _is_dry_run():
        resp = _dry_run_response(model=model, parsed=False, output_format=None)
        _emit_telemetry(agent, resp)
        return resp

    t_start = time.time()
    if _force_backend() == "local":
        raw = _local_create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools,
            thinking=thinking,
        )
        response = RouterResponse(
            content=raw["content"],
            text="",
            stop_reason=raw["stop_reason"],
            usage=raw["usage"],
            parsed_output=None,
            backend="local",
            used_subscription=False,
            fallback_reason=None,
            elapsed_sec=time.time() - t_start,
            retries=0,
            schema_failures=0,
            estimated_api_cost_usd=0.0,
            model=_local_model(model),
        )
        _emit_telemetry(agent, response)
        return response

    # Phase 0: Max tool-loop translation is Phase 2 (conditional). Currently
    # always-API for tool loops, with xAI/Gemini fallback when Anthropic is out
    # of credits / unavailable.
    fallback_reason = None
    if (quota_gate.should_try_subscription()
            and _credentials_present()
            and os.environ.get("HOGTRON_MAX_TOOL_LOOPS", "false").lower() == "true"):
        # Reserved flag for future Phase 2 work. Currently always-API.
        fallback_reason = "phase_2_not_enabled"

    return _do_create_via_api(
        agent=agent, model=model, system=system, messages=messages,
        tools=tools, thinking=thinking, max_tokens=max_tokens, api_key=api_key,
        t_start=t_start, fallback_reason=fallback_reason,
    )


def _do_create_via_api(*, agent: str, model: str, system: Any, messages: list,
                       tools: Optional[list], thinking: Optional[dict], max_tokens: int,
                       api_key: Optional[str], t_start: float,
                       fallback_reason: Optional[str]) -> RouterResponse:
    providers = _fallback_providers()
    skip_anthropic = bool(providers) and provider_breaker.anthropic_in_cooldown()
    anthropic_exc: Optional[Exception] = None

    if skip_anthropic:
        fallback_reason = fallback_reason or "anthropic_cooldown"
    else:
        try:
            raw = _api_create(model=model, max_tokens=max_tokens, system=system,
                              messages=messages, tools=tools, thinking=thinking, api_key=api_key)
            provider_breaker.clear_anthropic_cooldown()
            return _create_response(agent=agent, model=model, raw=raw, t_start=t_start,
                                    fallback_reason=fallback_reason, backend="api",
                                    cost=_estimate_cost_usd(model, raw["usage"]))
        except Exception as e:
            if not (providers and _should_fallback(e)):
                raise
            anthropic_exc = e
            if _is_credit_exhaustion(e):
                provider_breaker.record_anthropic_exhausted(str(e)[:200])
            fallback_reason = "anthropic_credit_exhausted" if _is_credit_exhaustion(e) else "anthropic_unavailable"

    errors = []
    for provider in providers:
        try:
            raw = _openai_create(provider, max_tokens=max_tokens, system=system,
                                 messages=messages, tools=tools, thinking=thinking)
            return _create_response(agent=agent, model=provider.model, raw=raw, t_start=t_start,
                                    fallback_reason=fallback_reason, backend=provider.name, cost=0.0)
        except Exception as e:
            errors.append(f"{provider.name}: {e}")

    if anthropic_exc is not None:
        raise anthropic_exc
    raise RuntimeError("All LLM providers failed — " + " | ".join(errors))


def _create_response(*, agent: str, model: str, raw: dict, t_start: float,
                     fallback_reason: Optional[str], backend: str, cost: float) -> RouterResponse:
    response = RouterResponse(
        content=raw["content"],
        text="",  # tool loops aggregate text per-iteration; caller can compute
        stop_reason=raw["stop_reason"],
        usage=raw["usage"],
        parsed_output=None,
        backend=backend,
        used_subscription=False,
        fallback_reason=fallback_reason,
        elapsed_sec=time.time() - t_start,
        retries=0,
        schema_failures=0,
        estimated_api_cost_usd=cost,
        model=model,
    )
    _emit_telemetry(agent, response)
    return response


# ---------------------------------------------------------------------------
# Backend visibility — for tests + CLI inspection
# ---------------------------------------------------------------------------

def describe_routing_decision() -> dict:
    """Returns what the router WOULD do right now, without making a call."""
    return {
        "HOGTRON_TRY_MAX": os.environ.get("HOGTRON_TRY_MAX", "false"),
        "HOGTRON_FORCE_BACKEND": os.environ.get("HOGTRON_FORCE_BACKEND", ""),
        "HOGTRON_LLM_BACKEND": os.environ.get("HOGTRON_LLM_BACKEND", ""),
        "LOCAL_LLM_BASE_URL": _local_base_url(),
        "LOCAL_LLM_MODEL": os.environ.get("LOCAL_LLM_MODEL", ""),
        "HOGTRON_DRY_RUN": os.environ.get("HOGTRON_DRY_RUN", ""),
        "anthropic_api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "credentials_present": _credentials_present(),
        "credentials_path": str(_credentials_path()),
        "quota_gate_should_try": quota_gate.should_try_subscription(),
        "quota_gate_state": quota_gate.state_snapshot(),
        "fallback_providers": [p.name for p in _fallback_providers()],
        "anthropic_in_cooldown": provider_breaker.anthropic_in_cooldown(),
        "api_breaker_state": provider_breaker.snapshot(),
    }


if __name__ == "__main__":
    import sys as _sys
    cmd = _sys.argv[1] if len(_sys.argv) > 1 else "describe"
    if cmd == "describe":
        print(json.dumps(describe_routing_decision(), indent=2))
    else:
        print(f"unknown command: {cmd}")
        _sys.exit(1)
