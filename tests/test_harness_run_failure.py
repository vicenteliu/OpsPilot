"""A run that never happened is not a low score.

The evaluators that do not read the artifact — `must_not_contain`,
`rag_recall_at_k` — pass against nothing, so an empty artifact lands around
**0.270**, not 0. Three very different outcomes rendered as the same row:

| Cause | Reported |
|---|---|
| Anthropic HTTP 400 (`temperature` deprecated for this model) | `weighted_score 0.270 FAIL` |
| OpenRouter HTTP 429 (rate-limited upstream) | `weighted_score 0.270 FAIL` |
| The model genuinely produced unparseable JSON | `weighted_score 0.270 FAIL` |

Only the third is a statement about the model. In a table meant for comparing
models, the first two are noise wearing a number.

The discriminator is **output tokens**: an error with none means the model never
answered. An error with output is a real quality signal and keeps its score.

(The other half of #171 — the refused run left a trace holding only its opening
`state_change`, because the orchestrator's catch-all wrote no error event — is
pinned in `test_orchestrator.py`, where its fixtures live.)

See #171.
"""

from __future__ import annotations

from typing import Any

from opspilot.harness.reporter import run_failure
from opspilot.harness.types import EvalResult


def _result(**orchestrator: Any) -> EvalResult:
    return EvalResult(
        run_id="run_x",
        fixture_id="fix_x",
        fixture_version="1.0.0",
        playbook_ref="pb@1",
        model_ref="anthropic/claude-sonnet-5@current",
        ts="2026-08-18T00:00:00Z",
        evaluators=[],
        scores={"weighted": 0.27, "by_type": {}},
        passed=False,
        extensions={"orchestrator": orchestrator} if orchestrator else {},
    )


class TestRunFailure:
    def test_error_with_no_output_is_a_failed_run(self) -> None:
        failure = run_failure(
            _result(schema_valid=False, error="ProviderError: 400 …", output_tokens=0)
        )
        assert failure is not None
        assert "400" in failure

    def test_error_with_output_is_a_quality_signal_and_keeps_its_score(self) -> None:
        """Unparseable JSON means the model ran and answered badly. Score it."""
        assert (
            run_failure(_result(schema_valid=False, error="JSON parse error: …", output_tokens=812))
            is None
        )

    def test_a_clean_run_has_no_failure(self) -> None:
        assert run_failure(_result()) is None

    def test_schema_invalid_without_an_error_still_scores(self) -> None:
        assert run_failure(_result(schema_valid=False, error=None, output_tokens=400)) is None
