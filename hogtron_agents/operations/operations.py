"""Operations department head.

One agent. One entrypoint: do(brief). Dispatches by kind. Every kind here
hits an external system — pay attention to the autonomy ladder when wiring
Layer 2/3 callers. See ../docs/architecture.md.
"""
from __future__ import annotations

from typing import Callable, Optional

from .briefs import OperationsBrief, OperationsResult, OperationsKind
from .._shared.telemetry import TelemetrySink, NullSink, working
from . import _printify_upload

Handler = Callable[["Operations", OperationsBrief], OperationsResult]


class Operations:
    NAME = "Operations"

    def __init__(self, telemetry: Optional[TelemetrySink] = None):
        self.telemetry = telemetry or NullSink()
        self._handlers: dict[OperationsKind, Handler] = {
            "printify_upload": _do_printify_upload,
            "publish_etsy": _do_publish_etsy,
            "publish_shopify": _do_publish_shopify,
            "publish_pinterest": _do_publish_pinterest,
            "render_video": _do_render_video,
            "deploy_mockup": _do_deploy_mockup,
            "deploy_proposal": _do_deploy_proposal,
        }

    def do(self, brief: OperationsBrief) -> OperationsResult:
        handler = self._handlers.get(brief.kind)
        if handler is None:
            raise ValueError(f"Operations has no handler for kind={brief.kind!r}")
        with working(self.telemetry, self.NAME, f"do({brief.kind})"):
            return handler(self, brief)

    def register(self, kind: OperationsKind, handler: Handler) -> None:
        self._handlers[kind] = handler


# --- Handlers -----------------------------------------------------------

def _do_printify_upload(self: Operations, brief: OperationsBrief) -> OperationsResult:
    return _printify_upload.printify_upload(brief)


def _do_publish_etsy(self: Operations, brief: OperationsBrief) -> OperationsResult:
    """Port target: FactoryHQ/agents/marketer.py publish(). Single API call
    to Printify's publish_product endpoint that pushes a draft to the
    linked Etsy shop."""
    raise NotImplementedError(
        "publish_etsy pending migration from FactoryHQ/agents/marketer.py publish()"
    )


def _do_publish_shopify(self: Operations, brief: OperationsBrief) -> OperationsResult:
    """Net-new: push Printify draft to Shopify channel. Shopify account
    added 2026-05-12 — wire once Printify->Shopify connection is configured."""
    raise NotImplementedError("publish_shopify not yet implemented — net-new kind")


def _do_publish_pinterest(self: Operations, brief: OperationsBrief) -> OperationsResult:
    """Port target: FactoryHQ/agents/pinterester.py. Cross-post each
    published Etsy listing to relevant Pinterest boards. Pinterest API
    trial access still pending per project memory."""
    raise NotImplementedError(
        "publish_pinterest pending migration from FactoryHQ/agents/pinterester.py"
    )


def _do_render_video(self: Operations, brief: OperationsBrief) -> OperationsResult:
    """Port target: FactoryHQ/agents/distributor.py + tools/video.py. Ken
    Burns vertical MP4 from product mockups via ffmpeg + PIL compositor."""
    raise NotImplementedError(
        "render_video pending migration from FactoryHQ/agents/distributor.py"
    )


def _do_deploy_mockup(self: Operations, brief: OperationsBrief) -> OperationsResult:
    """Port target: hogtron-dashboard mockup deploy (Railway one-click).
    DO NOT change existing client mockup URLs — they're frozen per
    reference_infra_rules.md."""
    raise NotImplementedError(
        "deploy_mockup pending migration from hogtron-dashboard mockup deploy"
    )


def _do_deploy_proposal(self: Operations, brief: OperationsBrief) -> OperationsResult:
    """Port target: hogtron-dashboard proposal share URL publishing."""
    raise NotImplementedError(
        "deploy_proposal pending migration from hogtron-dashboard proposals"
    )
