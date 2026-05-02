"""Tests for ``opspilot.redaction``."""

from __future__ import annotations

from pathlib import Path

import pytest

from opspilot.errors import RedactionError
from opspilot.redaction import (
    DEFAULT_RULES_PATH,
    RedactionRule,
    Redactor,
)


# ──────────────────────────────────────────────────────────────────────────
#  Loading
# ──────────────────────────────────────────────────────────────────────────


class TestLoading:
    def test_default_rules_path_exists(self) -> None:
        assert DEFAULT_RULES_PATH.is_file(), f"missing default rules: {DEFAULT_RULES_PATH}"

    def test_from_yaml_loads_default(self) -> None:
        r = Redactor.from_yaml()
        assert len(r.rules) > 5
        assert r.rules_version is not None

    def test_from_yaml_missing_path(self, tmp_path: Path) -> None:
        with pytest.raises(RedactionError, match="redaction rules not found"):
            Redactor.from_yaml(tmp_path / "nope.yaml")


# ──────────────────────────────────────────────────────────────────────────
#  Rule matching
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def redactor() -> Redactor:
    return Redactor.from_yaml(secret=b"test-session-secret")


class TestRules:
    def test_email(self, redactor: Redactor) -> None:
        result = redactor.redact("Contact: vicente@example.com today")
        assert "vicente@example.com" not in result.text
        assert "[REDACTED:email:" in result.text
        assert any(h.placeholder_type == "email" for h in result.hits)

    def test_phone_cn(self, redactor: Redactor) -> None:
        result = redactor.redact("我的手机是 13800138000，请联系")
        assert "13800138000" not in result.text
        assert any(h.placeholder_type == "phone" for h in result.hits)

    def test_id_cn_18(self, redactor: Redactor) -> None:
        # 18 digits + checksum X (last char allowed)
        national_id = "11010119900307123X"
        result = redactor.redact(f"ID: {national_id}")
        assert national_id not in result.text
        assert any(h.placeholder_type == "national_id" for h in result.hits)

    def test_ipv4(self, redactor: Redactor) -> None:
        result = redactor.redact("Connect to 192.168.1.50 please")
        assert "192.168.1.50" not in result.text
        assert any(h.placeholder_type == "ipv4" for h in result.hits)

    def test_ipv4_exception_loopback_preserved(self, redactor: Redactor) -> None:
        # 127.0.0.1 is in the rule's exceptions list — must not be redacted
        result = redactor.redact("Local server at 127.0.0.1:8080")
        assert "127.0.0.1" in result.text
        assert not any(h.original == "127.0.0.1" for h in result.hits)

    def test_ipv4_exception_zero_preserved(self, redactor: Redactor) -> None:
        result = redactor.redact("Bind 0.0.0.0:80")
        assert "0.0.0.0" in result.text

    def test_aws_akid(self, redactor: Redactor) -> None:
        ak = "AKIAIOSFODNN7EXAMPLE"  # well-known AWS docs example
        result = redactor.redact(f"export AWS_ACCESS_KEY_ID={ak}")
        assert ak not in result.text
        assert any(h.placeholder_type == "aws_akid" for h in result.hits)

    def test_bearer_token(self, redactor: Redactor) -> None:
        result = redactor.redact("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.foo.bar")
        # Either bearer or jwt rule fires (both target similar patterns); accept either
        types = {h.placeholder_type for h in result.hits}
        assert "bearer" in types or "jwt" in types

    def test_jwt(self, redactor: Redactor) -> None:
        # Use a context that won't trigger the generic_secret_assignment rule
        # ("token=…" matches the latter by design — generic catches arbitrary
        # secret-shaped assignments). Plain context = jwt rule fires.
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        result = redactor.redact(f"signed payload: {token}")
        assert any(h.placeholder_type == "jwt" for h in result.hits)

    def test_pem_private_key_multiline(self, redactor: Redactor) -> None:
        pem = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEpAIBAAKCAQEAxxxxxxxxx\n"
            "yyyyyyyyyyyyyyyyyyyyy\n"
            "-----END RSA PRIVATE KEY-----"
        )
        result = redactor.redact(f"key:\n{pem}\nrest")
        assert "BEGIN RSA PRIVATE KEY" not in result.text
        assert any(h.placeholder_type == "private_key" for h in result.hits)

    def test_internal_hostname(self, redactor: Redactor) -> None:
        result = redactor.redact("Connect to web01.corp")
        assert "web01.corp" not in result.text
        assert any(h.placeholder_type == "hostname" for h in result.hits)


# ──────────────────────────────────────────────────────────────────────────
#  Determinism + structure
# ──────────────────────────────────────────────────────────────────────────


class TestPlaceholders:
    def test_same_input_same_placeholder(self, redactor: Redactor) -> None:
        # Same email twice in the same Redactor (same secret) gets same hash slot.
        text = "From a@x.com to a@x.com again"
        result = redactor.redact(text)
        # both occurrences replaced by identical placeholder
        ph_set = {h.placeholder for h in result.hits if h.placeholder_type == "email"}
        assert len(ph_set) == 1, f"expected 1 distinct placeholder, got {ph_set}"

    def test_different_secret_different_placeholder(self) -> None:
        r1 = Redactor.from_yaml(secret=b"sec-A")
        r2 = Redactor.from_yaml(secret=b"sec-B")
        ph1 = r1.redact("a@x.com").hits[0].placeholder
        ph2 = r2.redact("a@x.com").hits[0].placeholder
        assert ph1 != ph2

    def test_placeholder_format(self, redactor: Redactor) -> None:
        result = redactor.redact("a@x.com")
        h = result.hits[0]
        assert h.placeholder.startswith("[REDACTED:email:")
        assert h.placeholder.endswith("]")
        # 8-hex hash
        body = h.placeholder.removeprefix("[REDACTED:email:").rstrip("]")
        assert len(body) == 8
        assert all(c in "0123456789abcdef" for c in body)


class TestSummary:
    def test_no_hits_clean_text(self, redactor: Redactor) -> None:
        result = redactor.redact("This is a perfectly clean sentence.")
        assert result.text == "This is a perfectly clean sentence."
        assert result.hits == ()
        assert result.summary == {}

    def test_multi_rule_counts(self, redactor: Redactor) -> None:
        text = "u1@x.com u2@x.com phone 13800138000"
        result = redactor.redact(text)
        # 2 emails + 1 phone
        emails = [h for h in result.hits if h.placeholder_type == "email"]
        phones = [h for h in result.hits if h.placeholder_type == "phone"]
        assert len(emails) == 2
        assert len(phones) == 1
        assert sum(result.summary.values()) == 3


# ──────────────────────────────────────────────────────────────────────────
#  post_check_required: residual scan
# ──────────────────────────────────────────────────────────────────────────


class TestResidualCheck:
    def test_clean_after_redact(self, redactor: Redactor) -> None:
        text = "Email a@x.com and ip 192.168.1.5"
        out = redactor.redact(text)
        assert not redactor.has_residual_pii(out.text)

    def test_residual_in_raw_text(self, redactor: Redactor) -> None:
        assert redactor.has_residual_pii("a@x.com leaked")


# ──────────────────────────────────────────────────────────────────────────
#  Spec example fixture: redact a sample ticket end-to-end
# ──────────────────────────────────────────────────────────────────────────


class TestExampleTicket:
    def test_redacts_internal_hostname_in_ticket_body(self, redactor: Redactor) -> None:
        # Mirrors the original (pre-redaction) shape of the zh ticket sample
        # from examples/scn_ticket_summary_zh/session/inputs/ticket.json.
        # We test that internal hostnames + emails would be caught.
        ticket_body = (
            "今天上午 10 点开始连不上 VPN，"
            "联系 alice@corp.local，主机 vpn-prod01.corp"
        )
        result = redactor.redact(ticket_body)
        types = {h.placeholder_type for h in result.hits}
        # alice@corp.local -> email; vpn-prod01.corp -> hostname (matches .corp)
        assert "email" in types
        assert "hostname" in types


# ──────────────────────────────────────────────────────────────────────────
#  Construction details
# ──────────────────────────────────────────────────────────────────────────


class TestRuleParsing:
    def test_rule_from_dict_minimal(self) -> None:
        r = RedactionRule.from_dict(
            {
                "id": "rule.test",
                "pattern": r"\b\d{3}\b",
                "placeholder_type": "test",
            }
        )
        assert r.id == "rule.test"
        assert r.pattern.search("abc 123 def") is not None
        assert r.exceptions == ()

    def test_rule_with_exceptions(self) -> None:
        r = RedactionRule.from_dict(
            {
                "id": "rule.test",
                "pattern": r"\b\d{3}\b",
                "placeholder_type": "test",
                "exceptions": ["123", "456"],
            }
        )
        assert "123" in r.exceptions
