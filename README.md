# hogtron-agents

Shared department-head agents for HogTron Solutions. Imported by FactoryHQ, hogtron-dashboard, and any future product lines.

## Org

- **Creative** — visual production (shirts, PDFs, mockups, proposals, Canva)
- _Research, Marketing, Sales, Operations — to be added as pilots succeed_

## Install (editable, for local dev)

```
pip install -e C:\Users\sbilg\Code\hogtron-agents
```

## Usage

```python
from hogtron_agents.creative import Creative, CreativeBrief

creative = Creative()
asset = creative.design(CreativeBrief(
    kind="shirt",
    payload={"concept": "...", "phrase": "...", "mood": "..."},
))
```

`CreativeBrief.kind` dispatches to the right toolchain. All kinds share brand constants, Claude client, telemetry, and the IP guardrail (no raw scrape data accepted).

## Status

Pilot. Interface stable; `shirt` and `pdf_page` kinds wired as stubs pending migration of `FactoryHQ/agents/designer.py` and `pdf_designer.py`.
