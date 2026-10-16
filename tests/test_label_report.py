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
    incident_report_markdown,
    known_fix_report_markdown,
    percentile,
    recall_cut,
    report_markdown,
    row_state,
    run_engines,
    security_report_markdown,
    threshold,
    wilson,
)
from opspilot.label_set import LabelSetError
from opspilot.redaction import Redactor

REPO_ROOT = Path(__file__).resolve().parents[1]
D2 = load_question(REPO_ROOT / DECISIONS_DIR / "d2.yaml")
D1 = load_question(REPO_ROOT / DECISIONS_DIR / "d1.yaml")


def _row(i: int, label: str, confidence: str = "high", **kw: Any) -> dict[str, Any]:
    return {
        "id": f"LS1-{i:03d}",
        "subject": f"subject {i}",
        "body": f"body {i}",
        "channel": "portal",
        "work_item_type": label,
        "security": "no",
        "label_confidence": confidence,
        "answer_space": {"d2": D2.version, "d1": D1.version},
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

    def test_the_relabel_is_read_against_the_first_pass_not_the_reviewed_label(self) -> None:
        rows = [_row(i, "incident") for i in range(1, 11)]
        for r in rows:
            r["security"] = "no"  # LS1-001 reviewed from yes to no after the relabel
        relabels = [{"id": r["id"], "work_item_type": "incident", "security": "no"} for r in rows]
        relabels[0]["security"] = "yes"
        reviews = [{"id": "LS1-001", "before": "yes", "after": "no"}]
        md = report_markdown(
            rows, _records("e", {"LS1-001": ("incident", 0.9)}), relabels, D2, reviews
        )
        assert "security 10/10" in md  # the first pass said yes, and so did the relabel
        assert "## Security review" in md and "1 changed. The review was not blind" in md

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


# ── Decision 1: every labelled security item reaches a person (#225) ────────


class TestSecurity:
    def test_the_cut_is_the_lowest_p_yes_any_labelled_security_item_got(self) -> None:
        judged = [(0.9, True), (0.3, True), (0.6, True), (0.2, False), (0.35, False)]
        assert recall_cut(judged) == 0.3

    def test_no_cut_without_a_labelled_security_item(self) -> None:
        assert recall_cut([(0.4, False)]) is None

    def _rows(self) -> list[dict[str, Any]]:
        return [_row(i, "incident", security="yes" if i <= 4 else "no") for i in range(1, 11)]

    def test_reports_each_engine_s_cut_its_recall_and_its_false_alarms(self) -> None:
        rows = self._rows()
        jev = {r["id"]: ("yes", 0.9) for r in rows[:4]} | {r["id"]: ("no", 0.95) for r in rows[4:]}
        jev["LS1-002"] = ("no", 0.7)  # P(yes) 0.3 on a labelled yes: the cut
        jev["LS1-005"] = ("no", 0.6)  # P(yes) 0.4 on a labelled no: a false alarm
        model = {r["id"]: ("yes", 0.8) for r in rows[:4]} | {r["id"]: ("no", 0.9) for r in rows[4:]}
        records = _records("typesafe:jev-1.13.0", jev, runs=2) + _records(
            "playbook:m", model, runs=2
        )
        reviews = [
            {"id": "LS1-003", "before": "yes", "after": "yes"},
            {"id": "LS1-009", "before": "yes", "after": "no"},
        ]
        relabels = [{"id": "LS1-009", "work_item_type": "incident", "security": "yes"}]
        md = security_report_markdown(rows, records, D1, reviews, relabels)

        assert md.startswith(f"# {D1.version} on the label set")
        assert "10 rows is not a benchmark" in md
        assert "4 of 10 rows are labelled `security: yes`" in md
        assert "1 of 2 reviewed labels changed, and the review was not blind" in md
        assert "| typesafe:jev-1.13.0 | 20/0 | 90.0% |" in md  # LS1-002 answered no, twice
        # Cut | recall | stopped | false alarms among the labelled no
        assert "| typesafe:jev-1.13.0 | 0.300 | 8/8 (100.0%) | 10/20 (50.0%) | 2/12 (16.7%) |" in md
        assert "| playbook:m | 0.800 | 8/8 (100.0%) | 8/20 (40.0%) | 0/12 (0.0%) |" in md
        # LS1-009 was yes in the first pass, as in the relabel, before the review made it no.
        assert "- security 1/1 (95% CI" in md

    def test_a_d1_run_refuses_a_set_whose_security_column_is_unfinished(
        self, tmp_path: Path
    ) -> None:
        rows = self._rows()
        rows[3]["security"] = None
        with pytest.raises(LabelSetError, match="label every row first"):
            run_engines(
                rows, D1, [], out=tmp_path / "r.jsonl", redactor=Redactor.from_yaml(), timeout_s=1
            )

    def test_failed_calls_are_kept_out_and_counted(self) -> None:
        rows = self._rows()
        answers = {r["id"]: ("yes" if r["security"] == "yes" else "no", 0.9) for r in rows}
        records = _records("e", answers)
        records[0] |= {"answer": None, "probability": None, "error": "boom"}
        md = security_report_markdown(rows, records, D1, None)
        assert "| e | 9/1 | 100.0% |" in md
        assert "| e | 0.900 | 3/3 (100.0%) | 3/9 (33.3%) | 0/6 (0.0%) |" in md


def test_cli_reports_decision_1_from_its_own_runs_file(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from opspilot import cli

    rows = [_row(i, "incident", security="yes" if i <= 2 else "no") for i in range(1, 5)]
    answers = {r["id"]: ("yes" if r["security"] == "yes" else "no", 0.9) for r in rows}
    set_path, runs_path = tmp_path / "set.jsonl", tmp_path / "runs_d1.jsonl"
    set_path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    runs_path.write_text(
        "".join(json.dumps(r) + "\n" for r in _records("e", answers)), encoding="utf-8"
    )
    result = CliRunner().invoke(
        cli.app,
        [
            "labelset", "report", "--decision", "d1", "--no-call",
            "--set", str(set_path), "--runs", str(runs_path),
            "--relabel", str(tmp_path / "none.jsonl"), "--review", str(tmp_path / "none.jsonl"),
        ],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert f"# {D1.version} on the label set" in result.output
    assert "| e | 0.900 | 2/2 (100.0%) | 2/4 (50.0%) | 0/2 (0.0%) |" in result.output


def test_the_relabel_reads_security_against_the_d1_v1_label_kept_beside_the_new_one() -> None:
    rows = [_row(i, "incident") for i in range(1, 11)]
    rows[0] |= {"security": "no", "security_d1_v1": "yes"}  # d1-v2 turned it to no
    relabels = [{"id": r["id"], "work_item_type": "incident", "security": "no"} for r in rows]
    relabels[0]["security"] = "yes"  # the relabel was made against d1-v1
    md = report_markdown(rows, _records("e", {"LS1-001": ("incident", 0.9)}), relabels, D2)
    assert "security 10/10" in md


def test_the_d1_runs_file_is_named_by_its_answer_space_version() -> None:
    from opspilot.label_report import RUNS_PATH, runs_path

    assert runs_path(D2) == RUNS_PATH
    assert runs_path(D1).name == f"runs_{D1.version.replace('-', '_')}.jsonl"


# ── Decision 9: is a candidate page a known fix (#226) ───────────────────────

D9 = load_question(REPO_ROOT / DECISIONS_DIR / "d9.yaml")


def _page(n: int) -> dict[str, str]:
    return {"source_path": f"p{n}.md", "title": f"Page {n}", "excerpt": f"how to fix {n}"}


class _Says:
    """Answers each (row, page) from a table keyed by the page's path in the state."""

    name = "e"

    def __init__(self, p_yes: dict[str, float]) -> None:
        self.p_yes, self.states = p_yes, []

    def judge(self, question: Question, state: str, *, timeout_s: float) -> Judgment:
        self.states.append(state)
        p = next(v for k, v in self.p_yes.items() if f"({k})" in state)
        answer = "yes" if p >= 0.5 else "no"
        return Judgment(
            "d9", "d9-v1", answer, p if answer == "yes" else 1 - p, self.name, 5, 0.00001
        )


def test_d9_asks_each_engine_about_each_candidate_page(tmp_path: Path) -> None:
    rows = [
        _row(1, "incident", known_fix=["p1.md"], answer_space={"d2": "d2-v1", "d9": D9.version}),
        _row(2, "incident", known_fix=[], answer_space={"d2": "d2-v1", "d9": D9.version}),
    ]
    candidates = {"LS1-001": [_page(1), _page(2)], "LS1-002": [_page(3)]}
    engine = _Says({"p1.md": 0.9, "p2.md": 0.2, "p3.md": 0.1})
    out = tmp_path / "runs_d9.jsonl"
    made = run_engines(
        rows, D9, [engine], runs=1, out=out, redactor=Redactor.from_yaml(), timeout_s=1,
        candidates=candidates,
    )  # fmt: skip
    assert made == 3
    assert "subject 1" in engine.states[0] and "Handbook page: Page 1 (p1.md)" in engine.states[0]
    assert "how to fix 1" in engine.states[0]
    assert [r["page"] for r in map(json.loads, out.read_text().splitlines())] == [
        "p1.md",
        "p2.md",
        "p3.md",
    ]
    # A rerun pays for nothing twice.
    assert run_engines(
        rows, D9, [engine], runs=1, out=out, redactor=Redactor.from_yaml(), timeout_s=1,
        candidates=candidates,
    ) == 0  # fmt: skip


def _fix_records(engine: str, p_yes: dict[tuple[str, str], float], runs: int = 1) -> list[dict]:
    return [
        {
            "engine": engine, "run": n, "id": i, "page": page,
            "answer": "yes" if p >= 0.5 else "no", "probability": p if p >= 0.5 else 1 - p,
            "latency_ms": 10, "cost_usd": 0.00001, "error": None,
        }
        for n in range(1, runs + 1)
        for (i, page), p in p_yes.items()
    ]  # fmt: skip


def test_the_d9_report_sends_each_row_s_likeliest_page_when_it_clears_the_cut() -> None:
    rows = [_row(i, "incident", known_fix=["a.md"] if i <= 18 else []) for i in range(1, 21)]
    p_yes: dict[tuple[str, str], float] = {}
    for r in rows:
        right = r["id"] <= "LS1-018"
        p_yes[(r["id"], "a.md")] = 0.9 if right else 0.3
        p_yes[(r["id"], "b.md")] = 0.2
    p_yes[("LS1-019", "b.md")] = 0.95  # a confident page for a row with no fix
    md = known_fix_report_markdown(rows, _fix_records("e", p_yes), D9)

    assert md.startswith(f"# {D9.version} on the label set")
    assert "18 of 20 rows have a known fix among their candidates" in md
    # 18 right at 0.9, one wrong at 0.95: at 0.9, 18/19 = 94.7% < 95%; at 0.95, 0/1.
    assert "| e | none reaches 95.0% |" in md


def test_the_d9_cut_is_the_lowest_at_which_the_fixes_sent_are_95_percent_right() -> None:
    rows = [_row(i, "incident", known_fix=["a.md"] if i <= 17 else []) for i in range(1, 21)]
    p_yes = {}
    for r in rows:
        p_yes[(r["id"], "a.md")] = 0.9 if r["known_fix"] else 0.4
        p_yes[(r["id"], "b.md")] = 0.2
    md = known_fix_report_markdown(rows, _fix_records("e", p_yes), D9)
    # At 0.4 all 20 go out and 17 are right (85%); at 0.9 the 17 that go out are all right.
    # Threshold | fixes sent | right among sent | fixable rows given a right page | no-fix rows sent a page
    assert "| e | 0.900 | 17/20 (85.0%) | 17/17 (100.0%) | 17/17 (100.0%) | 0/3 (0.0%) |" in md


def test_cli_reports_decision_9_from_its_own_runs_file(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from opspilot import cli

    rows = [_row(i, "incident", known_fix=["a.md"] if i <= 2 else []) for i in range(1, 5)]
    p_yes = {(r["id"], "a.md"): (0.9 if r["known_fix"] else 0.2) for r in rows}
    set_path, runs_path = tmp_path / "set.jsonl", tmp_path / "runs_d9.jsonl"
    set_path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    runs_path.write_text(
        "".join(json.dumps(r) + "\n" for r in _fix_records("e", p_yes)), encoding="utf-8"
    )
    result = CliRunner().invoke(
        cli.app,
        [
            "labelset",
            "report",
            "--decision",
            "d9",
            "--no-call",
            "--set",
            str(set_path),
            "--runs",
            str(runs_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert f"# {D9.version} on the label set" in result.output
    assert "| e | 0.900 | 2/4 (50.0%) | 2/2 (100.0%) | 2/2 (100.0%) | 0/2 (0.0%) |" in result.output


def test_d9_refuses_a_row_with_no_candidate_pages(tmp_path: Path) -> None:
    rows = [_row(1, "incident", known_fix=[], answer_space={"d2": "d2-v1", "d9": D9.version})]
    with pytest.raises(LabelSetError, match="LS1-001 has no candidate pages"):
        run_engines(
            rows, D9, [_Says({})], runs=1, out=tmp_path / "r.jsonl",
            redactor=Redactor.from_yaml(), timeout_s=1, candidates={},
        )  # fmt: skip


def test_a_row_and_run_with_an_unanswered_page_is_left_out_of_the_d9_cut() -> None:
    rows = [_row(i, "incident", known_fix=["a.md"]) for i in range(1, 21)]
    p_yes = {(r["id"], "a.md"): 0.9 for r in rows} | {(r["id"], "b.md"): 0.2 for r in rows}
    records = [r for r in _fix_records("e", p_yes) if (r["id"], r["page"]) != ("LS1-001", "a.md")]
    records.append(_fix_records("e", {("LS1-001", "a.md"): 0.9})[0] | {"error": "timeout"})
    md = known_fix_report_markdown(rows, records, D9)
    # LS1-001 never had its fixing page answered: not counted as sent b.md, nor as missed.
    assert "| e | 0.900 | 19/19 (100.0%) | 19/19 (100.0%) | 19/19 (100.0%) | 0/0 (–) |" in md


def test_with_whole_pages_shows_each_candidate_its_redacted_page(tmp_path: Path) -> None:
    from opspilot.label_report import with_whole_pages

    (tmp_path / "net").mkdir()
    (tmp_path / "net" / "p1.md").write_text("# Page 1\n\nMail ops@example.com first.\n")
    offered = {"LS1-001": [_page(1) | {"source_path": "net/p1.md"}]}
    whole = with_whole_pages(offered, tmp_path, Redactor.from_yaml())
    shown = whole["LS1-001"][0]["excerpt"]
    assert shown.startswith("# Page 1") and "ops@example.com" not in shown
    assert offered["LS1-001"][0]["excerpt"] == "how to fix 1"  # the passage is left as it was
    with pytest.raises(LabelSetError, match="p2.md is not in"):
        with_whole_pages({"LS1-002": [_page(2)]}, tmp_path, Redactor.from_yaml())


def test_the_d9_report_says_what_the_engines_were_shown() -> None:
    rows = [_row(1, "incident", known_fix=["a.md"])]
    records = _fix_records("e", {("LS1-001", "a.md"): 0.9})
    assert "shown the passage the labeller saw" in known_fix_report_markdown(rows, records, D9)
    md = known_fix_report_markdown(rows, records, D9, whole_page=True)
    assert "shown the whole page" in md


def test_cli_keeps_whole_page_to_decision_9() -> None:
    from typer.testing import CliRunner

    from opspilot import cli

    result = CliRunner().invoke(
        cli.app, ["labelset", "report", "--decision", "d2", "--whole-page", "--no-call"]
    )
    assert result.exit_code == 1 and "--whole-page is for d9 only" in result.output


# ── Decisions 7 and 8: a Score on each Incident (#227) ───────────────────────

D7 = load_question(REPO_ROOT / DECISIONS_DIR / "d7.yaml")


def _incident(i: int, impact: str) -> dict[str, Any]:
    space = {"d2": D2.version, "d1": D1.version, "d7": D7.version, "d8": "d8-v1"}
    return _row(i, "incident", impact=impact, urgency="stopped", answer_space=space)


def test_the_score_report_gives_the_level_within_one_and_the_bar_to_clear() -> None:
    rows = [_incident(i, "single_user" if i <= 8 else "multiple_users") for i in range(1, 11)]
    answers = {r["id"]: ("single_user", 0.9) for r in rows[:8]}
    answers |= {"LS1-009": ("multiple_users", 0.8), "LS1-010": ("site_wide", 0.6)}
    md = incident_report_markdown(rows, _records("e", answers), D7)

    assert md.startswith(f"# {D7.version} on the label set's Incidents")
    assert "single_user 8, multiple_users 2, site_wide 0" in md
    assert "Always answering single_user would be 80.0% right" in md
    # 9 of 10 exactly right, all 10 within one level.
    assert "| e | 10/0 | 90.0% | 100.0% |" in md
    # Brier on the answer's probability: 8 × 0.1² + 0.2² + 0.6², over 10.
    assert "| 0.048 |" in md
    # Only labelled levels get a row; every level is a column.
    assert "| e | single_user (8) | 8 | 0 | 0 |" in md
    assert "| e | multiple_users (2) | 0 | 1 | 1 |" in md
    assert "site_wide (0)" not in md
    # At 0.8, 9 decided and all right; at 0.6 the wrong one comes in, 9/10 < 95%.
    assert "| e | 0.800 | 9/10 (90.0%) | 100.0% |" in md


def test_cli_reports_impact_on_the_incidents_only(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from opspilot import cli

    rows = [_incident(1, "single_user"), _row(2, "service_request"), _incident(3, "site_wide")]
    set_path, runs_path = tmp_path / "set.jsonl", tmp_path / "runs_d7.jsonl"
    set_path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    records = _records("e", {"LS1-001": ("single_user", 0.9), "LS1-003": ("site_wide", 0.7)})
    runs_path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    result = CliRunner().invoke(
        cli.app,
        ["labelset", "report", "--decision", "d7", "--no-call", "--set", str(set_path), "--runs", str(runs_path)],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "2 Incidents is not a benchmark" in result.output
    assert "| e | 2/0 | 100.0% | 100.0% |" in result.output


def test_the_score_report_needs_every_incident_labelled() -> None:
    rows = [_incident(1, "single_user"), _row(2, "incident")]
    with pytest.raises(LabelSetError, match="label every Incident's impact first"):
        incident_report_markdown(rows, [], D7)


def test_a_choice_s_report_has_no_within_one_level() -> None:
    d6 = load_question(REPO_ROOT / DECISIONS_DIR / "d6.yaml")
    space = {"d2": D2.version, "d1": D1.version, "d6": d6.version}
    rows = [
        _row(i, "incident", team="systems" if i <= 3 else "network", answer_space=space)
        for i in range(1, 5)
    ]
    answers = {r["id"]: ("systems", 0.9) for r in rows}
    md = incident_report_markdown(rows, _records("e", answers), d6)
    assert "Within one level" not in md
    assert "Always answering systems would be 75.0% right" in md
    assert "| e | 4/0 | 75.0% | 0.210 |" in md
    assert "| e | network (1) | 0 | 1 |" in md


def test_a_noul_s_report_finds_the_cut_at_which_its_asks_are_95_percent_right() -> None:
    """Decision 4 (#229) acts only on a `no` that stands: the ask goes out."""
    d4 = load_question(REPO_ROOT / DECISIONS_DIR / "d4.yaml")
    space = {"d2": D2.version, "d1": D1.version, "d4": d4.version}
    rows = [
        _row(i, "incident", enough="no" if i <= 3 else "yes", answer_space=space)
        for i in range(1, 11)
    ]
    answers = {r["id"]: ("yes", 0.9) for r in rows[3:]}
    answers |= {"LS1-001": ("no", 0.9), "LS1-002": ("no", 0.8), "LS1-003": ("yes", 0.6)}
    answers["LS1-004"] = ("no", 0.7)  # a wrong ask, less sure than the right ones
    md = incident_report_markdown(rows, _records("e", answers), d4)
    assert "## Asks: the lowest P(no)" in md
    # At 0.8 two asks go out, both right; at 0.7 the wrong one joins: 2/3.
    assert "| e | 0.800 | 2/10 | 100.0% | 2/3 | 0/7 |" in md


# ── Decision 3: already open, over its own items (#230) ──────────────────────

D3 = load_question(REPO_ROOT / DECISIONS_DIR / "d3.yaml")


def _ao_item(n: int, same: str) -> dict[str, Any]:
    keys = [f"LS1-{n:03d}", f"LS1-{n + 100:03d}"]
    return {
        "id": f"AO-{n:03d}",
        "subject": f"subject {n}",
        "body": f"body {n}",
        "channel": "chat",
        "candidates": [{"key": k, "subject": f"about {k}", "body": "it broke"} for k in keys],
        "same": same,
        "answer_space": {"d3": D3.version},
    }


def test_d3_asks_each_item_over_its_own_open_work_items(tmp_path: Path) -> None:
    from opspilot.judgment import open_items_question

    items = [_ao_item(1, "LS1-001"), _ao_item(2, "none")]
    asked: list[list[str]] = []

    class Picks:
        name = "e"

        def judge(self, question: Question, state: str, *, timeout_s: float) -> Judgment:
            asked.append(list(question.answers))
            return Judgment("d3", "d3-v1", next(iter(question.answers)), 0.9, "e", 5, 0.00001)

    redactor = Redactor.from_yaml()
    made = run_engines(
        items, D3, [Picks()], runs=1, out=tmp_path / "runs_d3.jsonl", redactor=redactor,
        timeout_s=1, ask_with=lambda i: open_items_question(D3, i["candidates"], redactor),
    )  # fmt: skip
    assert made == 2
    assert asked == [["LS1-001", "LS1-101", "none"], ["LS1-002", "LS1-102", "none"]]


def test_the_d3_report_finds_the_cut_at_which_the_matches_named_are_95_percent_right() -> None:
    from opspilot.label_report import already_open_report_markdown

    items = [_ao_item(n, f"LS1-{n:03d}" if n <= 10 else "none") for n in range(1, 21)]
    answers = {f"AO-{n:03d}": (f"LS1-{n:03d}", 0.9) for n in range(1, 10)}
    answers["AO-010"] = ("none", 0.6)  # a match missed
    answers |= {f"AO-{n:03d}": ("none", 0.8) for n in range(11, 20)}
    answers["AO-020"] = ("LS1-020", 0.7)  # a match named where there is none
    md = already_open_report_markdown(items, _records("e", answers), D3)
    assert "10 items repeat one of their five open Work items" in md
    assert "| e | a match (10) | 9 | 1 | 0 |" in md
    assert "| e | none (10) | – | 9 | 1 |" in md
    # At 0.9 nine matches are named, all right; at 0.7 the false one joins: 9/10.
    assert "| e | 0.900 | 9/20 | 100.0% | 9/10 | 0/10 |" in md


def test_a_wide_choice_s_report_gives_right_none_or_another_per_label() -> None:
    """r1 (#231): a column per catalog item would be unreadable."""
    from opspilot.catalog import catalog_question, load_catalog

    decisions = REPO_ROOT / DECISIONS_DIR
    r1 = catalog_question(decisions / "r1.yaml", load_catalog(decisions / "catalog.yaml"))
    space = {"d2": D2.version, "d1": D1.version, "r1": r1.version}
    rows = [
        _row(i, "service_request", catalog_item="loaner" if i <= 3 else "none", answer_space=space)
        for i in range(1, 6)
    ]
    answers = {"LS1-001": ("loaner", 0.9), "LS1-002": ("none", 0.6), "LS1-003": ("reimage", 0.5)}
    answers |= {"LS1-004": ("none", 0.8), "LS1-005": ("guest_wifi", 0.4)}
    md = incident_report_markdown(rows, _records("e", answers), r1, rows_are="service requests")
    assert md.startswith("# r1-v1 on the label set's service requests")
    assert "| Engine | Labelled (answers) | Right | Said none | Another |" in md
    assert "| e | loaner (3) | 1 | 1 | 1 |" in md
    assert "| e | none (2) | 1 | – | 1 |" in md
    # Named answers: loaner 0.9 (right), reimage 0.5, guest_wifi 0.4 (both wrong).
    assert "## Named: the lowest probability at which the answers other than `none`" in md
    assert "| e | 0.900 | 1/5 | 100.0% | 1/3 | 0/2 |" in md


def test_r2_s_cut_is_on_the_answers_that_are_not_request() -> None:
    """r2 (#293): `request`, like an answer below the cut, leaves the request path as it is."""
    r2 = load_question(REPO_ROOT / DECISIONS_DIR / "r2.yaml")
    space = {"d2": D2.version, "d1": D1.version, "r2": r2.version}
    labels = ["request", "request", "change", "incident"]
    rows = [
        _row(i, "service_request", really=lab, answer_space=space)
        for i, lab in enumerate(labels, 1)
    ]
    answers = {"LS1-001": ("request", 0.9), "LS1-002": ("change", 0.6)}
    answers |= {"LS1-003": ("change", 0.9), "LS1-004": ("incident", 0.8)}
    md = incident_report_markdown(rows, _records("e", answers), r2, idle="request")
    assert "answers other than `request`" in md
    # Named: change 0.9 (right), incident 0.8 (right), change 0.6 (wrong, a request).
    assert "| e | 0.800 | 2/4 | 100.0% | 2/2 | 0/2 |" in md
