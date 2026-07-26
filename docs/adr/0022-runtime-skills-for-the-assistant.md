# Runtime skills for the chat assistant

Status: accepted (2026-07-25)

The Chat/assist surface becomes an agentic IT-troubleshooting copilot. Part
of that is **Skills**: reusable, hand-authored troubleshooting packages the
assistant loads on demand to guide its work on a known problem. OpsPilot
already has a `SKILL.md`-based Skill concept, but it is auto-distillation-
centric (variants → harness-gated promotion → lineage in the iteration
engine) and — critically — **not wired into runs at all today**. This ADR
adds a hand-authored, runtime-loaded skill path.

## Decision

- **Hand-authored Skills live in `skills/<id>/SKILL.md`** — git-reviewable,
  like a Playbook. Frontmatter carries the id, a one-line "use-when"
  trigger, an allowed-tools list (the tools/MCP the skill may use), and a
  trust level; the body is the troubleshooting procedure.
- **Loaded at runtime via a `load_skill` tool (progressive disclosure).**
  The agent is given a compact catalog (skill name + "use-when" trigger)
  built from the frontmatter; when a problem matches, the model calls
  `load_skill(id)` and the full `SKILL.md` is injected into the
  conversation. This keeps context lean and scales to many skills.
- **Weak models fall back to retrieval-injection.** Models that can't drive
  tool-calling reliably get the best-matching skill retrieved and injected
  directly — the same split OpsPilot already makes for KB retrieval
  (`retrieval mode` `tool` vs `prefetch`).
- **Decoupled from the iteration/harness engine in v1.** Hand-authored
  skills are *not* harness-gated; the iteration engine stays a separate
  (currently run-unwired) path for evolving *distilled* skills. Two origins,
  one `SKILL.md` format.
- **Skills are advisory.** They guide the assistant; the human IT-staff
  **User** still decides. Authoring is an **admin** action (ADR-0020).

## Trade-off accepted

Hand-authored skills **skip the regression harness** that gates distilled-
skill promotion — chosen for authoring speed and because skills only guide,
not decide (same "admin owns validation" stance as ADR-0021). Progressive
disclosure needs decent tool-calling, hence the weak-model retrieval
fallback. Two skill systems now coexist (distilled+iterated vs
hand-authored+runtime); this ADR exists so a future reader isn't surprised
to find both.

## Consequences

- New `skills/` directory; a runtime loader + catalog in the chat agent.
- A loaded skill may restrict the agent to its declared tools and hint a
  model tier (see ADR-0023).
- Authored via an admin in-app editor (writes `SKILL.md`, producing a git
  diff like ADR-0021) with optional AI-assisted drafting.
