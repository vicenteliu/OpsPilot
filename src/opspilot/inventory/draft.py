"""Draft Assets from a fulfillment artifact's ``asset_draft`` block (ADR-0018).

Guardrails-first: the block is model-emitted and schema-bounded, quantity
is capped here as defense in depth, drafting is idempotent per Work item
ref, and every drafted Asset carries a ``drafted`` event naming the
session so a wrong draft is cheap to spot and delete.
"""

from __future__ import annotations

import logging
from typing import Any

from .store import InventoryStore

logger = logging.getLogger("opspilot.inventory.draft")

# Defense in depth on top of the schema's own 1–20 bound.
MAX_DRAFT_QUANTITY = 20


def draft_assets_from_result(
    store: InventoryStore, result: dict[str, Any], session_id: str
) -> list[str]:
    """Create requested-status Assets from a fulfillment artifact.

    Returns the created asset ids; empty when the artifact has no
    ``asset_draft``, no ``work_item_ref``, or the Work item already has
    Assets (idempotency — reruns and redeliveries never duplicate).
    """
    draft = result.get("asset_draft")
    ref = str(result.get("work_item_ref", ""))
    if not isinstance(draft, dict) or not ref:
        return []
    if store.list(work_item_ref=ref):
        logger.info("assets already exist for %s — drafting skipped", ref)
        return []
    try:
        quantity = int(draft.get("quantity", 1))
    except (TypeError, ValueError):
        quantity = 1
    quantity = max(1, min(quantity, MAX_DRAFT_QUANTITY))
    created: list[str] = []
    for _ in range(quantity):
        row = store.create(
            {
                "category": str(draft.get("category", "")),
                "brand_model": str(draft.get("brand_model", "")),
                "specs": str(draft.get("specs", "")),
                "work_item_ref": ref,
                "status": "requested",
            },
            actor=f"session:{session_id}",
            event_change="drafted",
            note=f"drafted from Service Request {ref}",
        )
        created.append(row["asset_id"])
    logger.info("drafted %d asset(s) for %s", len(created), ref)
    return created
