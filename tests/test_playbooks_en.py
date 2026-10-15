"""Load-validation for the English playbook variants (issue #56)."""

from pathlib import Path

from opspilot.orchestrator.types import load_playbook

REPO_ROOT = Path(__file__).resolve().parents[1]
PLAYBOOKS = REPO_ROOT / "playbooks"


def test_classify_work_item_en_loads() -> None:
    pb = load_playbook(PLAYBOOKS / "pb_classify_work_item_en")
    assert pb.id == "pb_classify_work_item_en"
    assert pb.output_schema == "work_item_classification_v1"
    assert "work_item_classification_v1" in pb.system_prompt
    assert "service_request" in pb.system_prompt


def test_request_fulfillment_en_loads() -> None:
    pb = load_playbook(PLAYBOOKS / "pb_request_fulfillment_en")
    assert pb.id == "pb_request_fulfillment_en"
    assert pb.output_schema == "request_fulfillment_v1"
    assert pb.tools[0].name == "kb_search"
    assert "request_fulfillment_v1" in pb.system_prompt


def test_ask_en_loads() -> None:
    """Decision 5 (#229): the ask is a Playbook's model's to write."""
    pb = load_playbook(PLAYBOOKS / "pb_ask_en")
    assert pb.id == "pb_ask_en"
    assert pb.output_schema == "work_item_ask_v1"
    assert "work_item_ask_v1" in pb.system_prompt
    assert pb.tools == []
