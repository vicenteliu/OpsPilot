"""WikiPage model and file I/O (PR-19).

A wiki page is a markdown file with a YAML frontmatter block:

    ---
    page_id: wpg_<sha8>
    slug: some-slug
    kind: summary
    ...
    ---

    ## TL;DR
    ...

``page_id`` is the sha8 of ``slug + "|" + body`` so it changes when either
the identity or the content changes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class WikiPage:
    """One wiki page (frontmatter + body).

    Mirrors docs/specs/wiki/schemas/wiki-page.schema.json.
    """

    page_id: str
    slug: str
    kind: str  # entity | concept | summary | comparison | synthesis
    title: str
    summary: str
    namespace: str
    classification: str
    language: str
    version: str
    created_at: str
    updated_at: str
    derived_from: dict[str, Any]
    outbound_links: list[str]
    inbound_link_count: int
    redacted: bool
    redaction_rules_version: str
    lifecycle_state: str  # draft | reviewed | live | stale | archived
    owner: str
    body: str
    tags: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    extensions: dict[str, Any] | None = None


def make_page_id(slug: str, body: str) -> str:
    """Compute ``wpg_<sha8>`` from slug + body (content-addressed)."""
    content = (slug + "|" + body).encode()
    digest = hashlib.sha256(content).hexdigest()[:8]
    return f"wpg_{digest}"


def write_page(page: WikiPage, path: Path) -> None:
    """Serialise *page* to *path* as YAML frontmatter + markdown body."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fm: dict[str, Any] = {
        "page_id": page.page_id,
        "slug": page.slug,
        "kind": page.kind,
        "title": page.title,
        "summary": page.summary,
        "namespace": page.namespace,
        "classification": page.classification,
        "language": page.language,
        "version": page.version,
        "created_at": page.created_at,
        "updated_at": page.updated_at,
        "tags": page.tags,
        "aliases": page.aliases,
        "derived_from": page.derived_from,
        "outbound_links": page.outbound_links,
        "inbound_link_count": page.inbound_link_count,
        "redacted": page.redacted,
        "redaction_rules_version": page.redaction_rules_version,
        "lifecycle_state": page.lifecycle_state,
        "owner": page.owner,
    }
    if page.extensions is not None:
        fm["extensions"] = page.extensions

    fm_str = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False)
    path.write_text(f"---\n{fm_str}---\n\n{page.body}\n", encoding="utf-8")


def read_page(path: Path) -> WikiPage:
    """Parse a wiki page file into a :class:`WikiPage`."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"No frontmatter in {path}")
    # Find closing ---
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError(f"Unclosed frontmatter in {path}")
    fm_str = text[4:end]
    body = text[end + 5 :].lstrip("\n")
    fm = yaml.safe_load(fm_str)
    return WikiPage(
        page_id=fm["page_id"],
        slug=fm["slug"],
        kind=fm["kind"],
        title=fm["title"],
        summary=fm["summary"],
        namespace=fm["namespace"],
        classification=fm["classification"],
        language=fm["language"],
        version=fm["version"],
        created_at=fm["created_at"],
        updated_at=fm["updated_at"],
        tags=fm.get("tags") or [],
        aliases=fm.get("aliases") or [],
        derived_from=fm["derived_from"],
        outbound_links=fm.get("outbound_links") or [],
        inbound_link_count=fm.get("inbound_link_count", 0),
        redacted=fm["redacted"],
        redaction_rules_version=fm["redaction_rules_version"],
        lifecycle_state=fm["lifecycle_state"],
        owner=fm["owner"],
        extensions=fm.get("extensions"),
        body=body,
    )
