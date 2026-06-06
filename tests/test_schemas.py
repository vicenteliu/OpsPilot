"""Tests for the schema registry + validation against every example."""

from __future__ import annotations

from pathlib import Path

import pytest

from opspilot.errors import SchemaError
from opspilot.schemas import (
    get_schema,
    infer_schema_name,
    iter_items,
    load_data,
    registry,
    validate,
)

# Schemas that absolutely must be registered for the project to be self-consistent.
REQUIRED_SCHEMAS = (
    "session",
    "trace-event",
    "kb-document",
    "kb-chunk",
    "retrieval-query",
    "fixture",
    "eval-result",
    "skill",
    "skill-registry",
    "tool-binding",
    "mcp-config",
    "distillation-recipe",
    "iteration",
    "skill-variant",
    "feedback-signal",
    "wiki-page",
    "wiki-link",
    "lint-issue",
    "provider-config",
    "incident_summary_v1",
    "request_fulfillment_v1",
    "work_item_classification_v1",
)


def _valid_incident() -> dict:
    """A minimal artifact that satisfies incident_summary_v1."""
    return {
        "schema_version": "incident_summary_v1",
        "work_item_ref": "INC-001",
        "work_item_type": "incident",
        "summary": "VPN unreachable site-wide since 10:00.",
        "symptoms": ["users cannot connect", "gateway unresponsive"],
        "scope": "site_wide",
        "tried_steps": ["restarted client"],
        "missing_fields": ["affected user list"],
        "tasks": [
            {
                "ref": "task-1",
                "action": "Restart the VPN gateway",
                "rationale": "Gateway unresponsive per runbook",
                "tier": "L2",
                "citations": ["kb-1"],
            },
            {
                "ref": "task-2",
                "action": "Notify affected users",
                "rationale": "Site-wide impact",
                "tier": "L1",
            },
            {
                "ref": "task-3",
                "action": "Open a vendor case",
                "rationale": "May be upstream",
                "tier": "L3",
            },
        ],
        "severity_suggested": "P1",
        "citations": [
            {"id": "kb-1", "chunk_id": "chk_abcd1234", "document_id": "doc_abcd1234"},
        ],
    }


class TestIncidentSummarySchema:
    def test_valid_instance_passes(self, repo_root: Path) -> None:
        validate("incident_summary_v1", _valid_incident(), repo_root=repo_root)

    def test_missing_work_item_type_fails(self, repo_root: Path) -> None:
        bad = _valid_incident()
        del bad["work_item_type"]
        with pytest.raises(SchemaError):
            validate("incident_summary_v1", bad, repo_root=repo_root)

    def test_bad_tier_fails(self, repo_root: Path) -> None:
        bad = _valid_incident()
        bad["tasks"][0]["tier"] = "L4"
        with pytest.raises(SchemaError):
            validate("incident_summary_v1", bad, repo_root=repo_root)

    def test_bad_task_ref_fails(self, repo_root: Path) -> None:
        bad = _valid_incident()
        bad["tasks"][0]["ref"] = "t1"
        with pytest.raises(SchemaError):
            validate("incident_summary_v1", bad, repo_root=repo_root)

    def test_fewer_than_three_tasks_fails(self, repo_root: Path) -> None:
        bad = _valid_incident()
        bad["tasks"] = bad["tasks"][:2]
        with pytest.raises(SchemaError):
            validate("incident_summary_v1", bad, repo_root=repo_root)

    def test_bad_severity_fails(self, repo_root: Path) -> None:
        bad = _valid_incident()
        bad["severity_suggested"] = "P5"
        with pytest.raises(SchemaError):
            validate("incident_summary_v1", bad, repo_root=repo_root)

    def test_ticket_summary_v1_alias_removed(self, repo_root: Path) -> None:
        # Deprecation window closed (#11): the alias is gone.
        assert "ticket_summary_v1" not in registry(repo_root)


def _valid_request() -> dict:
    """A minimal artifact that satisfies request_fulfillment_v1."""
    return {
        "schema_version": "request_fulfillment_v1",
        "work_item_ref": "REQ-001",
        "work_item_type": "service_request",
        "summary": "New hire needs VPN access provisioned.",
        "requested_item": "VPN access for a new employee",
        "approval_needed": True,
        "missing_fields": ["manager approver"],
        "tasks": [
            {
                "ref": "task-1",
                "action": "Create the VPN account",
                "rationale": "Standard onboarding step",
                "tier": "L1",
                "citations": ["kb-1"],
            },
        ],
        "citations": [
            {"id": "kb-1", "chunk_id": "chk_abcd1234", "document_id": "doc_abcd1234"},
        ],
    }


class TestRequestFulfillmentSchema:
    def test_valid_instance_passes(self, repo_root: Path) -> None:
        validate("request_fulfillment_v1", _valid_request(), repo_root=repo_root)

    def test_wrong_work_item_type_fails(self, repo_root: Path) -> None:
        bad = _valid_request()
        bad["work_item_type"] = "incident"
        with pytest.raises(SchemaError):
            validate("request_fulfillment_v1", bad, repo_root=repo_root)

    def test_missing_requested_item_fails(self, repo_root: Path) -> None:
        bad = _valid_request()
        del bad["requested_item"]
        with pytest.raises(SchemaError):
            validate("request_fulfillment_v1", bad, repo_root=repo_root)

    def test_approval_needed_must_be_bool(self, repo_root: Path) -> None:
        bad = _valid_request()
        bad["approval_needed"] = "yes"
        with pytest.raises(SchemaError):
            validate("request_fulfillment_v1", bad, repo_root=repo_root)

    def test_reuses_task_object_with_tier(self, repo_root: Path) -> None:
        bad = _valid_request()
        bad["tasks"][0]["tier"] = "L9"
        with pytest.raises(SchemaError):
            validate("request_fulfillment_v1", bad, repo_root=repo_root)

    def test_no_incident_fields_allowed(self, repo_root: Path) -> None:
        # additionalProperties:false — incident-only fields must be rejected.
        bad = _valid_request()
        bad["severity_suggested"] = "P2"
        with pytest.raises(SchemaError):
            validate("request_fulfillment_v1", bad, repo_root=repo_root)


class TestWorkItemClassificationSchema:
    def _valid(self) -> dict:
        return {
            "work_item_type": "incident",
            "confidence": 0.82,
            "rationale": "Reports a service outage, not a standard request.",
        }

    def test_valid_instance_passes(self, repo_root: Path) -> None:
        validate("work_item_classification_v1", self._valid(), repo_root=repo_root)

    def test_unknown_type_fails(self, repo_root: Path) -> None:
        bad = self._valid()
        bad["work_item_type"] = "problem"
        with pytest.raises(SchemaError):
            validate("work_item_classification_v1", bad, repo_root=repo_root)

    def test_confidence_out_of_range_fails(self, repo_root: Path) -> None:
        bad = self._valid()
        bad["confidence"] = 1.5
        with pytest.raises(SchemaError):
            validate("work_item_classification_v1", bad, repo_root=repo_root)

    def test_missing_rationale_fails(self, repo_root: Path) -> None:
        bad = self._valid()
        del bad["rationale"]
        with pytest.raises(SchemaError):
            validate("work_item_classification_v1", bad, repo_root=repo_root)


class TestRegistry:
    def test_required_schemas_present(self, repo_root: Path) -> None:
        reg = registry(repo_root)
        missing = [s for s in REQUIRED_SCHEMAS if s not in reg]
        assert not missing, f"missing schemas: {missing}; have: {sorted(reg)}"

    def test_each_schema_has_id_and_title(self, repo_root: Path) -> None:
        reg = registry(repo_root)
        for name, schema in reg.items():
            assert "$id" in schema, f"schema {name} missing $id"
            assert "title" in schema, f"schema {name} missing title"

    def test_get_schema_unknown_raises(self) -> None:
        with pytest.raises(SchemaError, match="not registered"):
            get_schema("definitely-not-a-real-schema")


class TestInferSchemaName:
    @pytest.mark.parametrize(
        "rel_path,expected",
        [
            # KB
            ("examples/scn_ticket_summary_zh/kb/doc-meta.json", "kb-document"),
            ("examples/scn_ticket_summary_zh/kb/chunks.jsonl", "kb-chunk"),
            # Retrieval
            ("examples/scn_ticket_summary_zh/retrieval/request.json", "retrieval-query"),
            ("examples/scn_ticket_summary_zh/retrieval/response.json", "retrieval-query"),
            # Session
            ("examples/scn_ticket_summary_zh/session/meta.yaml", "session"),
            ("examples/scn_ticket_summary_zh/session/trace.jsonl", "trace-event"),
            # Harness
            ("examples/scn_ticket_summary_zh/harness/fixture.json", "fixture"),
            ("examples/scn_ticket_summary_zh/harness/results.jsonl", "eval-result"),
            # Iteration
            ("examples/itr_ticket_summary_zh_v1_3_0/iteration/recipe.yaml", "iteration"),
            ("examples/itr_ticket_summary_zh_v1_3_0/iteration/record.yaml", "iteration"),
            ("examples/itr_ticket_summary_zh_v1_3_0/feedback/signals.jsonl", "feedback-signal"),
            (
                "examples/itr_ticket_summary_zh_v1_3_0/variants/var_9930d615/meta.yaml",
                "skill-variant",
            ),
            (
                "examples/itr_ticket_summary_zh_v1_3_0/eval/var_9930d615-results.jsonl",
                "eval-result",
            ),
        ],
    )
    def test_inference_table(self, rel_path: str, expected: str) -> None:
        assert infer_schema_name(Path(rel_path)) == expected

    @pytest.mark.parametrize(
        "rel_path",
        [
            # Templates dirs are skipped (humans only)
            "skills/templates/SKILL.template.md",
            "memory/templates/kb-config.template.yaml",
            # Schemas themselves are skipped
            "session/schemas/session.schema.json",
            # Sandbox leftovers prefixed `_`
            "examples/foo/_summary_pending.json",
        ],
    )
    def test_inference_skipped(self, rel_path: str) -> None:
        assert infer_schema_name(Path(rel_path)) is None


class TestExampleValidates:
    """Run every discovered (file, schema) pair through the validator.

    ``example_pair`` is parametrized in ``conftest.pytest_generate_tests``.
    """

    def test_validates(self, example_pair: tuple[Path, str], repo_root: Path) -> None:
        f, schema_name = example_pair
        data = load_data(f)
        for item in iter_items(data):
            validate(schema_name, item, repo_root=repo_root)
