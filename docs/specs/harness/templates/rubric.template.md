# Rubric — scoring rubric template for `scn_<scenario_id>`

> This rubric is used by both the **LLM judge** and **human spot checks**. The LLM judge must pin the judge model version and the hash of this rubric.
> The more specific the rubric, the more stable the judge; wherever possible, describe observable pass/fail characteristics.

## 0. Metadata

- **scenario_id**: `scn_ticket_summary_zh`
- **rubric_version**: `1.0.0`
- **language**: zh-CN
- **judge_model_pinned**: `anthropic/claude-haiku-4-5@2025-10` (do **not** use `latest`)

## 1. Task definition

Input: a redacted IT ticket (body plus attached log snippet).
Expected output: a structured summary JSON (see `expected_structured` in golden.template.json for the schema).

## 2. Dimensions

Each dimension is scored 0–4; the weighted total is normalized to [0, 1].

| Dimension | Weight | 0 points | 2 points | 4 points |
|---|---|---|---|---|
| **Symptom capture** | 0.25 | misses the error keywords | captures the primary keyword | captures primary + secondary keywords, aligned with the log |
| **Scope identification** | 0.15 | describes only the submitter | mentions "multiple users" | quantified description ("multiple users since 10:00 AM") |
| **Steps already tried** | 0.15 | missed | captures the main ones | captures all, deduplicated |
| **Missing fields** | 0.15 | none identified | identifies 1–2 | identifies ≥3 key missing fields |
| **Next-step suggestions** | 0.20 | none or generic | gives 1–2 | gives 3, all actionable |
| **Severity level** | 0.10 | clearly inconsistent with the scenario | reasonable | reasonable, with justification |

## 3. Pass / Fail determination

- **Pass**: weighted score ≥ 0.7 **and** none of the hard fails below
- **Hard fail (any one fails the case)**:
  - Output leaves `[REDACTED:` placeholders in the `summary` field
  - Output fabricates log content (error codes not present in the fixture)
  - Output treats redaction tokens from the fixture as real information

## 4. Judge prompt skeleton

```
You are the OpsPilot evaluator. Given the input ticket (fixture), the model output (output), the reference output (golden), and the rubric,
score each rubric dimension from 0 to 4 and fill in the hard_fail flags.
Return JSON only:
{
  "dimensions": {
    "symptom": 0-4,
    "scope": 0-4,
    "tried_steps": 0-4,
    "missing_fields": 0-4,
    "next_actions": 0-4,
    "severity": 0-4
  },
  "weighted_score": 0.0-1.0,
  "hard_fail": ["redaction_leak"|"fabricated_log"|...],
  "rationale": "<=200 characters"
}
```

## 5. Anti-bias

- Do not reward or penalize output **length** (unless the rubric explicitly says so)
- Do not deduct points because the output's **wording differs** from the golden; only check whether the dimensions are covered
- All else being equal, **concise and actionable > long and exhaustive**

## 6. Change log

| Version | Date | Change | Impact |
|---|---|---|---|
| 1.0.0 | 2026-05-01 | Initial version | Full regression baseline established |
