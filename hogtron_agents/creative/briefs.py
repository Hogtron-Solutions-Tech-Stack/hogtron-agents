"""Creative brief and asset types. The contract between callers and the department."""
from __future__ import annotations

from typing import Literal, Any, Optional
from pydantic import BaseModel, Field

BriefKind = Literal[
    "shirt",          # POD shirt design (Factory)
    "pdf_page",       # single PDF page layout (Factory PDF line)
    "mockup",         # client website mockup (Dashboard)
    "proposal_cover", # client proposal cover art (Dashboard)
    "canva_asset",    # Canva-driven asset (logos, social posts)
]


class CreativeBrief(BaseModel):
    """Inbound request to the Creative department.

    The IP guardrail lives here: payload must be a cleared brief, never raw
    scraped data. Research department is responsible for clearing.
    """
    kind: BriefKind
    payload: dict[str, Any]
    context: dict[str, Any] = Field(default_factory=dict)
    requester: Optional[str] = None  # which pipeline/caller asked


class CreativeAsset(BaseModel):
    """Outbound result. URLs, file paths, and metadata. Caller decides storage."""
    kind: BriefKind
    primary_url: Optional[str] = None
    file_path: Optional[str] = None
    artifacts: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
