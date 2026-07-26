"""Skill registry — hand-authored SKILL.md packages the assistant loads at runtime.

A **Skill** is an ``agent_skills/<id>/SKILL.md`` with YAML frontmatter (``id``,
``name``, a ``trigger`` "use-when" line, ``allowed_tools``, ``trust``) and a
markdown body (the troubleshooting procedure). The chat agent shows a compact
catalog and loads the full body on demand via the ``load_skill`` tool
(progressive disclosure); weak models get the best-matching skill injected.
Hand-authored and git-reviewable, decoupled from the iteration engine — see
ADR-0022.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_DEFAULT_TRUST = "internal"


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    trigger: str  # the one-line "use-when" description
    body: str  # the full procedure markdown
    allowed_tools: list[str] = field(default_factory=list)
    trust: str = _DEFAULT_TRUST

    def catalog_entry(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name, "trigger": self.trigger}


def write_skill_md(base_dir: Path, skill: Skill) -> Path:
    """Write ``<base_dir>/<skill.id>/SKILL.md`` (frontmatter + body); return its path.

    Round-trips through :func:`parse_skill_md` — a file this writes always parses
    back to an equal Skill. Used by the admin skill editor (ADR-0022).
    """
    fm = {
        "id": skill.id,
        "name": skill.name,
        "trigger": skill.trigger,
        "allowed_tools": list(skill.allowed_tools),
        "trust": skill.trust,
    }
    fm_str = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True)
    skill_dir = base_dir / skill.id
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    path.write_text(f"---\n{fm_str}---\n\n{skill.body.rstrip()}\n", encoding="utf-8")
    return path


def parse_skill_md(text: str, *, fallback_id: str) -> Skill:
    """Parse a SKILL.md (YAML frontmatter + markdown body). Raises on malformed input."""
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md is missing its frontmatter block")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("SKILL.md has an unclosed frontmatter block")
    fm = yaml.safe_load(text[4:end]) or {}
    body = text[end + 5 :].lstrip("\n")
    sid = str(fm.get("id") or fallback_id)
    return Skill(
        id=sid,
        name=str(fm.get("name") or sid),
        trigger=str(fm.get("trigger") or fm.get("use_when") or ""),
        body=body,
        allowed_tools=[str(t) for t in (fm.get("allowed_tools") or [])],
        trust=str(fm.get("trust") or _DEFAULT_TRUST),
    )


_WORD = re.compile(r"[a-z0-9]+")
# Drop short/common words so a shared "a"/"the"/"how" never counts as a match.
_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "you",
        "your",
        "how",
        "are",
        "this",
        "that",
        "with",
        "can",
        "cannot",
        "not",
        "when",
        "where",
        "what",
        "who",
        "why",
        "does",
        "did",
    }
)


def _tokens(s: str) -> set[str]:
    return {w for w in _WORD.findall(s.lower()) if len(w) >= 3 and w not in _STOPWORDS}


class SkillRegistry:
    """In-memory catalog of loaded Skills, keyed by id."""

    def __init__(self, skills: list[Skill], base_dir: Path | None = None) -> None:
        self._skills = list(skills)
        self._by_id = {s.id: s for s in skills}
        self.base_dir = base_dir  # where load() read from; where the editor writes

    @classmethod
    def load(cls, base_dir: Path) -> SkillRegistry:
        """Load every ``<base_dir>/<id>/SKILL.md``; skip malformed ones so a bad
        skill never breaks startup."""
        skills: list[Skill] = []
        if base_dir.is_dir():
            for sub in sorted(base_dir.iterdir()):
                md = sub / "SKILL.md"
                if md.is_file():
                    try:
                        skills.append(
                            parse_skill_md(md.read_text(encoding="utf-8"), fallback_id=sub.name)
                        )
                    except Exception:  # noqa: BLE001 — a bad skill must not break startup
                        continue
        return cls(skills, base_dir=base_dir)

    def __len__(self) -> int:
        return len(self._skills)

    @property
    def skills(self) -> list[Skill]:
        return list(self._skills)

    def get(self, skill_id: str) -> Skill | None:
        return self._by_id.get(skill_id)

    def catalog(self) -> list[dict[str, str]]:
        return [s.catalog_entry() for s in self._skills]

    def match(self, query: str) -> Skill | None:
        """Best skill for *query* by lexical overlap with name+trigger.

        A deliberately simple matcher for the weak-model path — enough to pick
        an obviously-relevant skill; returns None when nothing overlaps.
        """
        q = _tokens(query)
        if not q:
            return None
        best: Skill | None = None
        best_score = 0
        for s in self._skills:
            score = len(q & _tokens(f"{s.name} {s.trigger}"))
            if score > best_score:
                best, best_score = s, score
        return best if best_score > 0 else None
