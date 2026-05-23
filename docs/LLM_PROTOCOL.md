# HogTron LLM Routing Protocol

**Audience:** anyone (human or Claude Code) writing code that calls a Claude model across `hogtron-agents`, `Hogtron-Dashboard`, or `Hogtron-FactoryHQ`.

**Source of truth:** this document. The implementation lives in [`hogtron_agents/_shared/claude_router.py`](../hogtron_agents/_shared/claude_router.py).

---

## The rule

> **All Anthropic-shaped LLM calls go through `claude_router`. No direct `anthropic.Anthropic(...)` clients, no raw `requests.post("https://api.anthropic.com/...")`.**

If you are calling Claude (any Opus / Sonnet / Haiku model), you call the router. That is the entire protocol.

## Why it matters

The router is the single point where the platform decides whether a call hits the **Anthropic API** (costs tokens), the **Claude Max subscription** (no per-call cost, capped), or a **local Ollama model** (free, runs on the dev machine). Setting `HOGTRON_FORCE_BACKEND=local` is supposed to redirect every call to Ollama in one place. Any direct SDK or HTTP call **silently defeats that switch**, and the dev burns API tokens during what was meant to be a local-mode session.

## How to comply

### Drop-in replacement for `messages.create`

Wrong:
```python
import anthropic
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
resp = client.messages.create(model="claude-haiku-4-5-20251001", ...)
```

Right:
```python
from hogtron_agents._shared import claude_router
resp = claude_router.route_messages_create(
    agent="my_app.my_feature",          # short label for the router log
    model="claude-haiku-4-5-20251001",
    system=SYSTEM_PROMPT,
    messages=[{"role": "user", "content": prompt}],
    max_tokens=4000,
)
text = "".join(
    getattr(b, "text", "") or ""
    for b in (resp.content or [])
    if getattr(b, "type", None) == "text"
)
```

### Drop-in replacement for structured `.parse`

```python
from hogtron_agents._shared import claude_router
resp = claude_router.route_messages_parse(
    agent="my_app.my_feature",
    model="claude-haiku-4-5-20251001",
    system=SYSTEM_PROMPT,
    messages=[{"role": "user", "content": prompt}],
    output_format=MyPydanticSchema,
    max_tokens=4000,
)
my_obj: MyPydanticSchema = resp.parsed_output
```

### Calling from Hogtron-Dashboard

`Hogtron-Dashboard/config.py` injects `~/Code/hogtron-agents` into `sys.path` at import time, so `from hogtron_agents._shared import claude_router` works as long as `config` is imported first (it always is — every dashboard module imports it). Import the router lazily inside the function if you want to avoid coupling import order.

## The router's env-var contract

| Env var | Purpose | Default |
|---|---|---|
| `HOGTRON_FORCE_BACKEND` | `local` \| `api` \| `max` — hard override | unset |
| `HOGTRON_LLM_BACKEND` | Alias for the above | unset |
| `HOGTRON_TRY_MAX` | Try Claude Max first, fall back to API on failure | unset |
| `HOGTRON_DRY_RUN` | Skip all LLM calls, return stub responses | unset |
| `ANTHROPIC_API_KEY` | Used when backend is `api` | required for API mode |
| `LOCAL_LLM_BASE_URL` | OpenAI-compatible endpoint | `http://127.0.0.1:11434/v1` |
| `LOCAL_LLM_MODEL` | Local model name (e.g. `qwen2.5:3b`) | required for local mode |
| `LOCAL_LLM_API_KEY` | Optional bearer token for local endpoint | unset |
| `LOCAL_LLM_TIMEOUT_SECONDS` | HTTP timeout | `180` |
| `LOCAL_LLM_RETRIES` | Retry attempts | `1` |
| `LOCAL_LLM_USE_JSON_SCHEMA` | Use json_schema response_format (only some backends support this) | `false` |
| `HOGTRON_FALLBACK_PROVIDERS` | Comma-separated cloud fallback order after Anthropic | `gemini,xai` |
| `XAI_API_KEY` / `XAI_MODEL` | xAI fallback key + model | model `grok-4-fast-non-reasoning` |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | Gemini fallback key + model (OpenAI-compat endpoint) | model `gemini-2.5-flash` |
| `HOGTRON_API_COOLDOWN_SEC` | How long to skip Anthropic after a credit-exhaustion error | `900` |

To run an agent fully locally: set `HOGTRON_FORCE_BACKEND=local` + `LOCAL_LLM_MODEL=qwen2.5:3b` and start Ollama. Nothing else changes.

## Cross-provider fallback (Anthropic → Gemini → xAI)

When the **Anthropic API path** fails because the account is **out of credits**
(HTTP 400 "credit balance is too low"), is **rate-limited** (429), hits a **5xx**,
or the connection drops, the router automatically retries the same request on
the cloud fallback providers — Gemini, then xAI — using its existing
OpenAI-compatible translation layer (so tool loops and structured output both
work). A bad API key or a malformed-request 400 does **not** fall back (it would
fail identically everywhere).

To avoid eating a dead Anthropic round-trip on every call once credits run dry,
a file-backed **circuit breaker** (`provider_breaker.py`) records the
credit-exhaustion error and sends subsequent calls straight to the fallback for
`HOGTRON_API_COOLDOWN_SEC`; a successful Anthropic call clears it. The fallback
is a no-op when no `XAI_API_KEY` / `GEMINI_API_KEY` is set — the router stays
Anthropic-only, exactly as before. The response's `backend` field reports which
provider actually answered (`api` / `max` / `local` / `gemini` / `xai`).

> **Hardware note:** the primary dev machine has ~7.9 GB RAM. `qwen2.5:14b` will not load. Default to `qwen2.5:3b` unless you've checked the host.

## Known carve-outs (do not "fix" these)

These bypass the router on purpose. Don't route them through `claude_router`.

1. **`Hogtron-Dashboard/tools/seo_package/agent_runner.py`** — uses the **Claude Agent SDK** (`claude_agent_sdk`), which only speaks to the real Anthropic API. The SDK runs plugins, slash commands, and tool-use loops that local Ollama cannot reproduce. The file refuses to run when `HOGTRON_FORCE_BACKEND=local` (see [`agent_runner.py:29-33`](../../Hogtron-Dashboard/tools/seo_package/agent_runner.py)). That guard **is** the protocol-compliant behavior for this module.
2. **Gemini / xAI providers** in the SEO audit tools — `_call_gemini` and `_call_xai` in `tools/seo_audit.py` and `tools/combined_seo_geo_audit.py` (and the standalone Geo-Auditor service) hit Google and xAI directly as their *primary* analysis path, selected by `SEO_AUDIT_PROVIDER`. Those callers stay raw HTTP. Note this is distinct from the router's own Gemini/xAI **fallback**: the router now does know how to dispatch them (via its OpenAI-compatible layer) when an Anthropic call fails — but only as a fallback for Anthropic-shaped calls, not as a primary provider you select.

If you find another bypass that isn't on this list, it's a bug — route it through `claude_router` and add a memory entry so the next session remembers.

## What "wrong" looks like — grep before you commit

Run this in the repo before you commit a feature that calls Claude:

```bash
git grep -nE 'anthropic\.Anthropic\(|"https://api\.anthropic\.com'
```

The only matches should be inside `claude_router.py` itself. Anything else is a bypass.

## History

- 2026-05-20 — Dashboard `tools/seo_audit.py` and `tools/combined_seo_geo_audit.py` and agents `research/_seo_audit.py` migrated off direct HTTP onto the router. `Hogtron-Dashboard/tools/llm_router.py` (a parallel mini-router) was deleted; the shared `claude_router` now handles local mode too.
- 2026-05-23 — Added cross-provider fallback to the router: on Anthropic credit-exhaustion / rate-limit / 5xx / connection failure, both `route_messages_parse` and `route_messages_create` retry on Gemini then xAI via the OpenAI-compatible layer. New `provider_breaker.py` circuit breaker skips Anthropic for `HOGTRON_API_COOLDOWN_SEC` after a credit-exhaustion 400. Dashboard `seo_audit.py` / `combined_seo_geo_audit.py` also gained their own primary-provider fallback chain (they were single-provider and 400'd when Anthropic credits ran out).
