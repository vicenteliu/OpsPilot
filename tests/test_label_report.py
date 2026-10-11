"""The label set's report: both engines on decision 2, measured as SPEC §7 asks (#224)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from opspilot.errors import ProviderError
from opspilot.judgment import DECISIONS_DIR, Judgment, Question, load_question
from opspilot.label_report import (
    brier,
    percentile,
    report_markdown,
    row_state,
    run_engines,
    threshold,
    wilson,
)
from opspilot.label_set import LabelSetError
from opspilot.redaction import Redactor

REPO_ROOT = Path(__file__).resolve().parents[1]
D2 = load_question(REPO_ROOT / DECISIONS_DIR / "d2.yaml")


def _row(i: int, label: str, confidence: str = "high", **kw: Any) -> dict[str, Any]:
    return {
        "id": f"LS1-{i:03d}",
        "subject": f"subject {i}",
        "body": f"body {i}",
        "channel": "portal",
        "work_item_type": label,
        "security": "no",
        "label_confidence": confidence,
        "answer_space": {"d2": "d2-v1", "d1": "d1-v1"},
        **kw,
    }


class _Engine:
    """Answers from a table keyed by the row id it finds in the state, and counts calls."""

    def __init__(
        self, name: str, answers: dict[str, tuple[str, float]], fail: frozenset[str] = frozenset()
    ):
        self.name, self.answers, self.fail = name, answers, fail
        self.calls: list[str] = []

    def judge(self, question: Question, state: str, *, timeout_s: float) -> Judgment:
        row_id = state.split()[2]  # "Work item LS1-001 (portal, ?)"
        self.calls.append(row_id)
        if row_id in self.fail:
            raise ProviderError("timed out after 20.0s")
        answer, p = self.answers[row_id]
        return Judgment(question.id, question.version, answer, p, self.name, 100, 0.00002)


ROWS = [_row(1, "incident"), _row(2, "service_request"), _row(3, "incident", "low")]


class TestRowState:
    def test_a_row_is_rendered_as_the_run_renders_a_work_item_and_redacted(self) -> None:
        row = _row(7, "incident", body="Reach me at jane.doe@corp.example.net please")
        state = row_state(row, Redactor.from_yaml())
        assert state.startswith("Work item LS1-007 (portal, ?)")
        assert "Subject: subject 7" in state
        assert "jane.doe@corp.example.net" not in state

    def test_the_labels_never_reach_an_engine(self) -> None:
        state = row_state(_row(1, "service_request", label_note="looks like access"), Redactor([]))
        assert "service_request" not in state and "looks like access" not in state


class TestRunEngines:
    def test_every_engine_answers_every_row_each_run_and_each_call_is_saved(
        self, tmp_path: Path
    ) -> None:
        out = tmp_path / "runs.jsonl"
        a = _Engine("typesafe:jev", {r["id"]: (r["work_item_type"], 0.9) for r in ROWS})
        b = _Engine("playbook:m", {r["id"]: ("incident", 0.7) for r in ROWS})
        made = run_engines(ROWS, D2, [a, b], runs=2, out=out, redactor=Redactor([]), timeout_s=5)
        assert made == 12 and len(a.calls) == len(b.calls) == 6
        records = [json.loads(line) for line in out.read_text().splitlines()]
        assert len(records) == 12
        first = records[0]
        assert {k: first[k] for k in ("engine", "run", "id", "answer", "probability")} == {
            "engine": "typesafe:jev",
            "run": 1,
            "id": "LS1-001",
            "answer": "incident",
            "probability": 0.9,
        }
        assert first["error"] is None and first["latency_ms"] == 100

    def test_a_rerun_resumes_and_pays_for_nothing_twice(self, tmp_path: Path) -> None:
        out = tmp_path / "runs.jsonl"
        answers = {r["id"]: ("incident", 0.8) for r in ROWS}
        run_engines(
            ROWS, D2, [_Engine("e", answers)], runs=1, out=out, redactor=Redactor([]), timeout_s=5
        )
        again = _Engine("e", answers)
        made = run_engines(ROWS, D2, [again], runs=2, out=out, redactor=Redactor([]), timeout_s=5)
        assert made == 3 and again.calls == ["LS1-001", "LS1-002", "LS1-003"]

    def test_a_failed_call_is_recorded_as_a_failure_not_an_answer(self, tmp_path: Path) -> None:
        out = tmp_path / "runs.jsonl"
        e = _Engine("e", {r["id"]: ("incident", 0.8) for r in ROWS}, fail=frozenset({"LS1-002"}))
        run_engines(ROWS, D2, [e], runs=1, out=out, redactor=Redactor([]), timeout_s=5)
        [failed] = [json.loads(x) for x in out.read_text().splitlines() if "LS1-002" in x]
        assert failed["answer"] is None and failed["error"] == "timed out after 20.0s"

    def test_a_failed_call_is_retried_on_the_next_run(self, tmp_path: Path) -> None:
        out = tmp_path / "runs.jsonl"
        answers = {r["id"]: ("incident", 0.8) for r in ROWS}
        run_engines(
            ROWS,
            D2,
            [_Engine("e", answers, fail=frozenset({"LS1-002"}))],
            runs=1,
            out=out,
            redactor=Redactor([]),
            timeout_s=5,
        )
        again = _Engine("e", answers)
        run_engines(ROWS, D2, [again], runs=1, out=out, redactor=Redactor([]), timeout_s=5)
        assert again.calls == ["LS1-002"]
        # The file keeps the failure as well as the retry: it happened, and the
        # report counts it.
        tries = [r for r in map(json.loads, out.read_text().splitlines()) if r["id"] == "LS1-002"]
        assert [r["error"] for r in tries] == ["timed out after 20.0s", None]

    def test_refuses_a_set_that_is_not_finished_or_labelled_against_another_version(
        self, tmp_path: Path
    ) -> None:
        e = _Engine("e", {})
        unlabelled = [*ROWS, {**_row(4, "incident"), "work_item_type": None}]
        with pytest.raises(LabelSetError, match="label every row"):
            run_engines(
                unlabelled, D2, [e], runs=1, out=tmp_path / "r", redactor=Redactor([]), timeout_s=5
            )
        other = [*ROWS, _row(4, "incident", answer_space={"d2": "d2-v0"})]
        with pytest.raises(LabelSetError, match="d2-v0"):
            run_engines(
                other, D2, [e], runs=1, out=tmp_path / "r", redactor=Redactor([]), timeout_s=5
            )
        assert e.calls == []


class TestMeasures:
    def test_brier_scores_the_probability_of_the_first_answer(self) -> None:
        # "incident" at 0.9 on an incident: (0.9-1)^2; "service_request" at 0.8 on
        # an incident: P(incident) = 0.2, (0.2-1)^2.
        assert brier([("incident", 0.9, "incident")], positive="incident") == pytest.approx(0.01)
        assert brier([("service_request", 0.8, "incident")], positive="incident") == pytest.approx(
            0.64
        )

    def test_the_threshold_is_the_lowest_p_whose_routed_items_are_95_percent_right(self) -> None:
        # 20 right at 0.9, one wrong at 0.8, one wrong at 0.95.
        judged = [(0.9, True)] * 20 + [(0.8, False), (0.95, False)]
        # At 0.8 all 22 route, 20/22 = 90.9%; at 0.9, 21 route, 20/21 = 95.2%.
        assert threshold(judged) == (0.9, 21, 20)

    def test_no_threshold_when_no_cut_reaches_95_percent(self) -> None:
        assert threshold([(0.9, True), (0.9, False)]) is None

    def test_wilson_gives_the_interval_ten_rows_deserve(self) -> None:
        lo, hi = wilson(9, 10)
        assert lo == pytest.approx(0.596, abs=0.001) and hi == pytest.approx(0.982, abs=0.001)
        assert wilson(10, 10)[1] == pytest.approx(1.0)

    def test_percentile_is_nearest_rank(self) -> None:
        assert percentile([10, 20, 30, 40], 0.5) == 20
        assert percentile(list(range(1, 101)), 0.95) == 95


def _records(engine: str, answers: dict[str, tuple[str, float]], runs: int = 1) -> list[dict]:
    return [
        {
            "engine": engine,
            "run": n,
            "id": i,
            "answer": a,
            "probability": p,
            "latency_ms": 100 * n,
            "cost_usd": 0.00002,
            "error": None,
        }
        for n in range(1, runs + 1)
        for i, (a, p) in answers.items()
    ]


class TestReport:
    def test_reports_each_engine_with_its_caveat_and_the_relabel(self) -> None:
        rows = [
            _row(i, "incident" if i % 2 else "service_request", "low" if i < 3 else "high")
            for i in range(1, 21)
        ]
        right = {r["id"]: (r["work_item_type"], 0.97) for r in rows}
        wrong_one = {**right, "LS1-001": ("service_request", 0.6)}
        records = _records("typesafe:jev-1.13.0", right, runs=3) + _records(
            "playbook:m", wrong_one, runs=3
        )
        relabels = [
            {"id": r["id"], "work_item_type": r["work_item_type"], "security": "no"}
            for r in rows[:10]
        ]
        relabels[0]["work_item_type"] = "service_request"
        md = report_markdown(rows, records, relabels, D2)
        assert "20 rows is not a benchmark" in md
        assert "| typesafe:jev-1.13.0 | 60/0 | 100.0% |" in md
        assert "| playbook:m | 60/0 | 95.0% |" in md
        assert "type 9/10 (95% CI 59.6%–98.2%)" in md
        assert "security 10/10" in md

    def test_failed_calls_are_counted_and_kept_out_of_accuracy(self) -> None:
        rows = [_row(1, "incident"), _row(2, "incident")]
        records = _records("e", {"LS1-001": ("incident", 0.9)})
        records.append(
            {**records[0], "id": "LS1-002", "answer": None, "probability": None, "error": "boom"}
        )
        md = report_markdown(rows, records, None, D2)
        assert "| e | 1/1 | 100.0% |" in md
        assert "no relabel" in md

    def test_a_record_for_a_row_not_in_the_set_is_refused(self) -> None:
        records = _records("e", {"LS1-099": ("incident", 0.9)})
        with pytest.raises(LabelSetError, match="LS1-099"):
            report_markdown([_row(1, "incident")], records, None, D2)


class TestCli:
    def _files(self, tmp_path: Path) -> tuple[Path, Path]:
        rows = [_row(1, "incident"), _row(2, "service_request")]
        path = tmp_path / "set.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        runs = tmp_path / "runs.jsonl"
        records = _records(
            "typesafe:jev-1.13.0", {"LS1-001": ("incident", 0.9), "LS1-002": ("incident", 0.6)}
        )
        runs.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        return path, runs

    def test_no_call_reports_from_the_runs_file_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from typer.testing import CliRunner

        from opspilot import cli

        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        path, runs = self._files(tmp_path)
        out = tmp_path / "report.md"
        result = CliRunner().invoke(
            cli.app,
            [
                "labelset",
                "report",
                "--no-call",
                "--set",
                str(path),
                "--runs",
                str(runs),
                "--relabel",
                str(tmp_path / "none.jsonl"),
                "--out",
                str(out),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "| typesafe:jev-1.13.0 | 2/0 | 50.0% |" in result.output
        # At 0.9 the one routed item is right; at 0.6 both route and one is wrong.
        assert "| typesafe:jev-1.13.0 | 0.900 | 1/2 (50.0%) | 100.0% |" in result.output
        assert out.read_text(encoding="utf-8") in result.output

    def test_without_a_typesafe_key_nothing_is_called(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from typer.testing import CliRunner

        from opspilot import cli

        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        path, _ = self._files(tmp_path)
        runs = tmp_path / "fresh.jsonl"
        result = CliRunner().invoke(
            cli.app, ["labelset", "report", "--set", str(path), "--runs", str(runs)]
        )
        assert result.exit_code == 1
        assert "TYPESAFE_API_KEY is not set" in result.output
        assert not runs.exists()
