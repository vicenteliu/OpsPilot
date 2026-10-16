"""The service catalog: the request path's answer space and its Lookups (ADR-0040, #231)."""

from __future__ import annotations

from pathlib import Path

import pytest

from opspilot.catalog import catalog_question, entitled, load_catalog
from opspilot.judgment import DECISIONS_DIR, JudgmentError

REPO_ROOT = Path(__file__).resolve().parents[1]
DECISIONS = REPO_ROOT / DECISIONS_DIR


def test_the_sample_catalog_states_every_lookup() -> None:
    catalog = load_catalog(DECISIONS / "catalog.yaml")
    assert catalog.version == "catalog-v1" and len(catalog.items) == 16
    vpn = catalog.items["vpn_access"]
    assert (vpn.approval, vpn.entitled, vpn.stock, vpn.automated) == ("manager", None, None, False)
    assert catalog.items["loaner"].stock == "laptop"
    assert catalog.items["new_hardware"].stock == "requested"
    assert catalog.items["admin_rights"].entitled == ("engineering",)
    assert {i.id for i in catalog.items.values() if i.automated} == {
        "password_reset",
        "software_install",
        "guest_wifi",
    }


def test_which_item_is_a_choice_over_the_catalog_then_none() -> None:
    catalog = load_catalog(DECISIONS / "catalog.yaml")
    question = catalog_question(DECISIONS / "r1.yaml", catalog)
    assert list(question.answers) == [*catalog.items, "none"]
    assert question.answers["loaner"].startswith("Loaner device: A loaner laptop")


def test_a_question_measured_on_another_catalog_is_refused(tmp_path: Path) -> None:
    text = (DECISIONS / "catalog.yaml").read_text(encoding="utf-8")
    other = tmp_path / "catalog.yaml"
    other.write_text(text.replace("version: catalog-v1", "version: catalog-ours"), encoding="utf-8")
    with pytest.raises(JudgmentError, match="measure it again"):
        catalog_question(DECISIONS / "r1.yaml", load_catalog(other))


def test_an_approval_no_lookup_knows_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "catalog.yaml"
    path.write_text(
        "version: x\nitems:\n  a:\n    name: A\n    description: d\n    approval: ceo\n",
        encoding="utf-8",
    )
    with pytest.raises(JudgmentError, match="approval is one of"):
        load_catalog(path)


@pytest.mark.parametrize(
    ("item", "role", "expected"),
    [
        ("vpn_access", None, True),  # anyone may ask
        ("admin_rights", "Engineering", True),
        ("admin_rights", "finance", False),
        ("admin_rights", None, None),  # the role is not known: a person checks
    ],
)
def test_entitlement_is_looked_up_from_the_submitter_s_role(
    item: str, role: str | None, expected: bool | None
) -> None:
    catalog = load_catalog(DECISIONS / "catalog.yaml")
    assert entitled(catalog.items[item], role) is expected
