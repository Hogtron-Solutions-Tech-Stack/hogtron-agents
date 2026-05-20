# hogtron-agents

## LLM routing — read before touching any Claude call

**All Anthropic-shaped LLM calls go through `hogtron_agents/_shared/claude_router.py`.** Do not write `anthropic.Anthropic(...)` clients or raw `requests.post("https://api.anthropic.com/...")` calls anywhere else. Direct calls silently defeat `HOGTRON_FORCE_BACKEND=local` and burn API tokens during local-mode sessions.

Full protocol, code patterns, env vars, and known carve-outs: [`docs/LLM_PROTOCOL.md`](docs/LLM_PROTOCOL.md).

Quick check before committing:
```bash
git grep -nE 'anthropic\.Anthropic\(|"https://api\.anthropic\.com'
```
The only matches should be inside `_shared/claude_router.py`.

## Sibling repos that share this router

- `~/Code/Hogtron-Dashboard` — injects this repo into sys.path at `config.py:8-10`.
- `~/Code/Hogtron-FactoryHQ` — same router, agents use `route_messages_parse`.
