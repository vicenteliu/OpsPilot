"""PII redaction.

Driven by ``session/templates/redaction-rules.template.yaml`` from the spec.
Each rule = ``id + description + pattern + placeholder_type + exceptions``.

Algorithm:

1. For every rule, find every match in the input text.
2. Sort matches by start offset; on overlap, the rule that appears first
   in the YAML wins (``first_match_wins``).
3. Replace each accepted match with ``[REDACTED:<placeholder_type>:<sha8>]``
   where the sha8 is ``sha256(secret + original)[:8]`` — letting the same
   raw value collapse to the same placeholder *within a session* while
   preventing cross-session correlation when a secret is supplied.

Returns text + structured hits + a per-rule summary.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml

from .errors import RedactionError

# Spec rules live in the OpsPilot spec tree (not under src/opspilot/).
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
DEFAULT_RULES_PATH: Final[Path] = (
    _REPO_ROOT / "session" / "templates" / "redaction-rules.template.yaml"
)


@dataclass(frozen=True, slots=True)
class RedactionRule:
    """Compiled form of one entry in ``rules:`` from redaction-rules.yaml."""

    id: str
    description: str
    pattern: re.Pattern[str]
    placeholder_type: str
    exceptions: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, d: dict) -> "RedactionRule":
        # The yaml patterns embed ``(?i)`` inline where needed; we compile
        # WITHOUT extra flags. Multi-line patterns (e.g. PEM private keys)
        # use ``[\s\S]+?`` explicitly so they don't depend on DOTALL.
        return cls(
            id=d["id"],
            description=d.get("description", ""),
            pattern=re.compile(d["pattern"]),
            placeholder_type=d["placeholder_type"],
            exceptions=tuple(d.get("exceptions") or ()),
        )


@dataclass(frozen=True, slots=True)
class RedactionPolicy:
    audit_on_hit: bool = True
    first_match_wins: bool = True
    post_check_required: bool = True


@dataclass(frozen=True, slots=True)
class RedactionHit:
    rule_id: str
    placeholder_type: str
    original: str
    placeholder: str
    # (start, end) char offsets in the *input* text (before redaction).
    span: tuple[int, int]


@dataclass(frozen=True, slots=True)
class RedactionResult:
    text: str
    hits: tuple[RedactionHit, ...]
    summary: dict[str, int]  # rule_id → count

    @property
    def hit_count(self) -> int:
        return len(self.hits)

    def types_seen(self) -> set[str]:
        return {h.placeholder_type for h in self.hits}


# ──────────────────────────────────────────────────────────────────────────


class Redactor:
    """Apply a set of redaction rules to text."""

    def __init__(
        self,
        rules: list[RedactionRule],
        *,
        policy: RedactionPolicy | None = None,
        secret: bytes = b"",
        rules_version: str | None = None,
    ) -> None:
        self.rules = rules
        self.policy = policy or RedactionPolicy()
        self.secret = secret
        self.rules_version = rules_version

    # ── Loaders ────────────────────────────────────────────────────────

    @classmethod
    def from_yaml(
        cls,
        path: Path | None = None,
        *,
        secret: bytes = b"",
    ) -> "Redactor":
        """Load rules from a yaml file matching the spec template format."""
        path = path or DEFAULT_RULES_PATH
        if not path.is_file():
            msg = f"redaction rules not found: {path}"
            raise RedactionError(msg)
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        rules = [RedactionRule.from_dict(r) for r in data.get("rules", [])]
        policy_data = data.get("policies") or {}
        policy = RedactionPolicy(
            audit_on_hit=policy_data.get("audit_on_hit", True),
            first_match_wins=policy_data.get("first_match_wins", True),
            post_check_required=policy_data.get("post_check_required", True),
        )
        return cls(
            rules,
            policy=policy,
            secret=secret,
            rules_version=str(data.get("version", "")) or None,
        )

    # ── Core API ───────────────────────────────────────────────────────

    def _placeholder_for(self, original: str, placeholder_type: str) -> str:
        h = hashlib.sha256(self.secret + original.encode("utf-8")).hexdigest()[:8]
        return f"[REDACTED:{placeholder_type}:{h}]"

    def redact(self, text: str) -> RedactionResult:
        # 1) Collect all matches across rules.
        rule_priority = {r.id: i for i, r in enumerate(self.rules)}
        candidates: list[tuple[int, int, RedactionRule, str]] = []
        for rule in self.rules:
            for m in rule.pattern.finditer(text):
                original = m.group(0)
                if original in rule.exceptions:
                    continue
                candidates.append((m.start(), m.end(), rule, original))

        # 2) Sort by start, then by length descending (longest / most specific
        #    match wins at the same offset — e.g. an 18-digit national ID beats
        #    a 16-digit prefix-only phone-number match), then by rule priority
        #    as final tiebreaker (earlier-defined rule wins on exact ties).
        candidates.sort(
            key=lambda c: (c[0], -(c[1] - c[0]), rule_priority[c[2].id])
        )

        # 3) Filter overlaps with first_match_wins semantics.
        accepted: list[tuple[int, int, RedactionRule, str]] = []
        last_end = -1
        for start, end, rule, original in candidates:
            if start < last_end:
                continue  # overlaps an already-accepted match
            accepted.append((start, end, rule, original))
            last_end = end

        # 4) Build the output string and the hit list.
        out_parts: list[str] = []
        hits: list[RedactionHit] = []
        cursor = 0
        for start, end, rule, original in accepted:
            out_parts.append(text[cursor:start])
            placeholder = self._placeholder_for(original, rule.placeholder_type)
            out_parts.append(placeholder)
            hits.append(
                RedactionHit(
                    rule_id=rule.id,
                    placeholder_type=rule.placeholder_type,
                    original=original,
                    placeholder=placeholder,
                    span=(start, end),
                )
            )
            cursor = end
        out_parts.append(text[cursor:])

        redacted = "".join(out_parts)
        summary = dict(Counter(h.rule_id for h in hits))
        return RedactionResult(text=redacted, hits=tuple(hits), summary=summary)

    # ── Convenience ────────────────────────────────────────────────────

    def has_residual_pii(self, text: str) -> bool:
        """Run the rules again on *text*; return True if any rule still matches.

        Used by the spec's ``post_check_required`` policy: after redaction the
        output should be free of any rule's pattern.
        """
        for rule in self.rules:
            for m in rule.pattern.finditer(text):
                if m.group(0) not in rule.exceptions:
                    return True
        return False
