"""Wiki promote engine (PR-25).

Advances a wiki page through its lifecycle:
    draft → reviewed → live → stale → archived

Usage::

    result = promote_page("some-slug", PromoteConfig(wiki_root=Path("wiki")))

The page file is rewritten in-place; index.md and log.md are updated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..errors import OpsPilotError
from ..timeutil import now_rfc3339
from .index import WikiLogEntry, append_log, update_index
from .page import make_page_id, read_page, write_page

# Valid forward transitions (any other combo is rejected)
_VALID_TRANSITIONS: set[tuple[str, str]] = {
    ("draft", "reviewed"),
    ("draft", "live"),
    ("reviewed", "live"),
    ("live", "stale"),
    ("live", "archived"),
    ("stale", "archived"),
}

_VALID_STATES = {"draft", "reviewed", "live", "stale", "archived"}


@dataclass(frozen=True)
class PromoteConfig:
    wiki_root: Path
    target_state: str = "live"
    owner: str = "wiki-maintainer@opspilot"


@dataclass
class PromoteResult:
    slug: str
    page_path: Path
    old_state: str
    new_state: str
    new_version: str
    skipped: bool = False
    skip_reason: str = ""


class PromoteError(OpsPilotError):
    """Raised for unrecoverable promote failures."""


def _bump_minor(version: str) -> str:
    """Increment minor component: '1.0.0' → '1.1.0'."""
    parts = version.split(".")
    if len(parts) != 3:
        return version
    try:
        return f"{parts[0]}.{int(parts[1]) + 1}.0"
    except ValueError:
        return version


def _append_changelog(body: str, version: str, state: str, now: str) -> str:
    """Append a changelog bullet under ## Changelog; add section if absent."""
    bullet = f"- v{version} ({now[:10]}): promoted to {state}\n"
    if "## Changelog" in body:
        # Insert bullet at the end of the Changelog section
        return re.sub(r"(## Changelog\n)", r"\1" + bullet, body, count=1)
    return body.rstrip() + f"\n\n## Changelog\n{bullet}"


def promote_page(slug: str, config: PromoteConfig) -> PromoteResult:
    """Promote *slug* to ``config.target_state``.

    Returns a :class:`PromoteResult` with ``skipped=True`` when the page is
    already at the target state or the slug cannot be found.
    Raises :class:`PromoteError` for invalid transitions or I/O failures.
    """
    if config.target_state not in _VALID_STATES:
        raise PromoteError(f"Unknown target state: {config.target_state!r}")

    # Locate the page across all kind subdirectories
    matches = list(config.wiki_root.glob(f"pages/*/{slug}.md"))
    if not matches:
        return PromoteResult(
            slug=slug,
            page_path=Path("."),
            old_state="",
            new_state="",
            new_version="",
            skipped=True,
            skip_reason=f"page '{slug}' not found in {config.wiki_root}/pages/",
        )

    page_path = matches[0]
    page = read_page(page_path)
    old_state = page.lifecycle_state

    if old_state == config.target_state:
        return PromoteResult(
            slug=slug,
            page_path=page_path,
            old_state=old_state,
            new_state=old_state,
            new_version=page.version,
            skipped=True,
            skip_reason=f"page '{slug}' is already '{old_state}'",
        )

    if (old_state, config.target_state) not in _VALID_TRANSITIONS:
        raise PromoteError(
            f"Invalid transition for '{slug}': {old_state!r} → {config.target_state!r}. "
            f"Valid transitions: {sorted(_VALID_TRANSITIONS)}"
        )

    now = now_rfc3339()
    new_version = _bump_minor(page.version)
    new_body = _append_changelog(page.body, new_version, config.target_state, now)

    page.lifecycle_state = config.target_state
    page.updated_at = now
    page.version = new_version
    page.body = new_body
    page.page_id = make_page_id(slug, new_body)

    write_page(page, page_path)
    update_index(config.wiki_root, page)
    append_log(
        config.wiki_root,
        WikiLogEntry(
            op="promote",
            subject=slug,
            pages_updated=1,
            notes=f"{old_state}→{config.target_state} v{new_version}",
        ),
    )

    return PromoteResult(
        slug=slug,
        page_path=page_path,
        old_state=old_state,
        new_state=config.target_state,
        new_version=new_version,
    )
