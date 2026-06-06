# Rubric — `scn_ticket_summary_en` Scoring Standard

## Metadata

- **scenario_id**: `scn_ticket_summary_en`
- **rubric_version**: `1.0.0`
- **language**: en
- **judge_model_pinned**: `anthropic-claude/claude-haiku-4-5@2025-10`
- **rubric_hash**: `sha256:7a2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c` (validated at runtime)

## Task definition

**Input**: a redacted IT ticket (body + log attachment snippet) plus retrieved KB chunks (with citations).
**Expected output**: structured JSON conforming to `incident_summary_v1`; every citation must resolve to a `source_path:line_range`.

## Scoring dimensions (aligned with expected_structured)

Each dimension scored 0-4; weighted and normalized to [0, 1].

| Dimension | Weight | 0 | 2 | 4 |
|---|---|---|---|---|
| **Symptom capture** | 0.20 | misses key error | catches main keyword | main + secondary keywords aligned with log |
| **Scope identification** | 0.15 | only the submitter | mentions "multiple users" | quantified ("since 09:00, multiple users") |
| **Tried steps** | 0.10 | missed | major ones | all captured, deduplicated |
| **Missing fields** | 0.10 | not identified | 1-2 items | ≥3 key missing items |
| **Next actions** | 0.15 | 0-1 generic | 2 actionable | ≥3 actionable |
| **Severity** | 0.05 | clearly off | reasonable | reasonable + cites rationale |
| **Citation validity** | 0.25 | none | present but mislocated | accurate to chk_e3fe2afe / SOP §2.1 |

## Pass / Fail

- **Pass**: weighted score ≥ 0.7 **and** no hard_fail
- **Hard fail (any of):**
  - `[REDACTED:` placeholder leaks into the `summary` field
  - Fabricates log content (an error code not in the fixture)
  - Citation points to a non-existent chunk_id or wrong line_range
  - Treats a redaction token as if it were real data

## Judge prompt skeleton

```
You are an OpsPilot evaluator. Given the fixture (input ticket), the model output, the
golden reference, and this rubric, score every dimension on a 0-4 scale, flag hard_fail
conditions, and return a JSON object:
{
  "dimensions": {
    "symptom": 0-4, "scope": 0-4, "tried_steps": 0-4,
    "missing_fields": 0-4, "tasks": 0-4,
    "severity": 0-4, "citation_validity": 0-4
  },
  "weighted_score": 0.0-1.0,
  "hard_fail": ["redaction_leak"|"fabricated_log"|"invalid_citation"|...],
  "rationale": "≤200 chars"
}
```

## Anti-bias notes

- Do not reward or penalize on length unless the rubric calls for it.
- Do not penalize wording that differs from the golden — only score dimension coverage.
- Concise & actionable > verbose & exhaustive.

## Change log

| Version | Date | Change |
|---|---|---|
| 1.0.0 | 2026-05-01 | Initial release; includes RAG citation_validity dimension |
