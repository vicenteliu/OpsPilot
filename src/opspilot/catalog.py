"""The service catalog (ADR-0040, #231): the request path's answer space, and its Lookups.

Requests are pre-defined: the thinking was done when the catalog was written.
So which item a request is for is the one Judgment (r1.yaml, a Choice over the
items), and what the item says, who approves it, who may ask for it, what to
count in stock and whether it is automated, is looked up, never decided by a
model. An organisation brings its own catalog; ``catalog.yaml`` beside the
decisions is a sample (ADR-0038: the catalog is not handbook content).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import yaml

from .judgment import JudgmentError, Question, load_question, with_candidates

CATALOG_FILE: Final = "catalog.yaml"
CATALOG_ITEM_FILE: Final = "r1.yaml"
APPROVERS: Final = ("none", "manager", "owner", "security")


@dataclass(frozen=True)
class CatalogItem:
    id: str
    name: str
    description: str
    fields: tuple[str, ...]  # what fulfilling it needs to know
    approval: str  # one of APPROVERS
    entitled: tuple[str, ...] | None  # submitter roles that may ask for it; None for all
    stock: str | None  # an Asset category, or "requested" for the one asked for
    automated: bool


@dataclass(frozen=True)
class Catalog:
    version: str
    items: dict[str, CatalogItem]


def load_catalog(path: Path) -> Catalog:
    """Read a catalog; refuse an item that leaves a Lookup unanswerable."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items: dict[str, CatalogItem] = {}
    for item_id, spec in (data.get("items") or {}).items():
        spec = spec or {}
        if not spec.get("name") or not spec.get("description"):
            raise JudgmentError(f"{path}: {item_id} needs a name and a description")
        approval = spec.get("approval", "none")
        if approval not in APPROVERS:
            raise JudgmentError(
                f"{path}: {item_id}'s approval is one of {APPROVERS}, not {approval!r}"
            )
        entitled = spec.get("entitled", "all")
        items[str(item_id)] = CatalogItem(
            id=str(item_id),
            name=str(spec["name"]),
            description=str(spec["description"]),
            fields=tuple(str(f) for f in spec.get("fields") or ()),
            approval=approval,
            entitled=None if entitled == "all" else tuple(str(r).lower() for r in entitled),
            stock=str(spec["stock"]) if spec.get("stock") else None,
            automated=bool(spec.get("automated", False)),
        )
    if not items:
        raise JudgmentError(f"{path}: the catalog has no items")
    return Catalog(version=str(data.get("version", "")), items=items)


def catalog_question(path: Path, catalog: Catalog) -> Question:
    """Which catalog item, asked over ``catalog``: each item an answer, then `none`.

    Refused when the question was measured on another catalog version: a cut
    measured on one set of items says nothing about another.
    """
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if data.get("catalog_version") != catalog.version:
        raise JudgmentError(
            f"{path} is for catalog {data.get('catalog_version')!r}, but the catalog is "
            f"{catalog.version!r}: give it a new version and measure it again"
        )
    question = load_question(path)
    return with_candidates(
        question, {i.id: f"{i.name}: {i.description}" for i in catalog.items.values()}
    )


def entitled(item: CatalogItem, submitter_role: str | None) -> bool | None:
    """Whether the submitter may ask for ``item``; None when their role is not known."""
    if item.entitled is None:
        return True
    if not submitter_role:
        return None
    return submitter_role.strip().lower() in item.entitled
