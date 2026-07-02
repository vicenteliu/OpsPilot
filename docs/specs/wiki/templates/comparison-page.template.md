---
# Comparison page — comparison of multiple objects/options
# Equivalent to schemas/wiki-page.schema.json (kind=comparison)

page_id: "wpg_33333333"
slug: "radius-vs-ldap-auth"
kind: "comparison"
title: "RADIUS vs AD LDAP — Choosing an Authentication Backend"
summary: "Compares RADIUS and AD LDAP for VPN authentication: differences in latency, availability, observability, and operational boundaries."
namespace: "opspilot:public-kb"
classification: "internal"
language: "zh-CN"
version: "1.0.0"
created_at: "2026-05-01T10:00:00Z"
updated_at: "2026-05-01T10:00:00Z"

tags: ["comparison", "auth", "radius", "ldap"]
aliases: ["Authentication backend comparison"]

derived_from:
  sources:
    - kind: "kb_document"
      ref: "doc_88a277cf"
      sha256: "sha256:88a277cf857f9fdee36c4b8272b40bdfa121e3a9526956f9f21cc7198f3e456d"
      line_start: 42
      line_end: 42
  parent_pages: []

outbound_links: []
inbound_link_count: 0

redacted: true
redaction_rules_version: "1.0.0"

lifecycle_state: "live"
owner: "vicente@example.com"
collaborators: []

kb_registration:
  kb_doc_id: null
  registered_at: null
  embedding_model: null
  chunk_count: null

lint_state:
  last_linted_at: null
  open_issue_ids: []

extensions:
  comparison:
    subjects:
      - "RADIUS"
      - "AD LDAP"
    criteria:
      - "Protocol ports"
      - "Latency"
      - "Observability"
      - "High-availability approach"
      - "Operational ownership"
---

# RADIUS vs AD LDAP

## Subjects

- **RADIUS**: the classic AAA protocol, ports UDP 1812 (auth) / 1813 (accounting)
- **AD LDAP**: LDAP-based directory service, ports TCP 389 (plaintext) / 636 (TLS)

## Comparison table

| Dimension | RADIUS | AD LDAP |
|---|---|---|
| Ports | UDP 1812/1813 | TCP 389/636 |
| Protocol semantics | AAA (authentication + authorization + accounting) | Directory queries (authenticate via simple bind or SASL) |
| Latency | Low (UDP; a single RTT is typically < 50ms on the intranet) | Medium (TCP handshake + possible TLS handshake) |
| High availability | proxy / multiple servers | DC replication |
| Failure observability | Clear accounting/rejection reasons | Bind error codes + LDAP 32/49/53 etc. |
| Common VPN usage | Front-line authentication (username+password / OTP) | Queried by the RADIUS backend |
| Troubleshooting keywords | `Access-Reject`, `silently discarded` | `LDAP_INVALID_CREDENTIALS` (49), `LDAP_NO_SUCH_OBJECT` (32) |

## Verdict / when to use which

- Most corporate VPN scenarios: **RADIUS in front, AD LDAP behind** (RADIUS forwards requests to AD LDAP) — see [[vpn-gateway-corp]]
- Plain application login (HTTP APIs, internal tools): **bind directly against AD LDAP**
- Need accounting / session counting → RADIUS (accounting packets)
- Need to store rich user attributes → AD LDAP

## Cross-links

- compares → [[radius-auth-backend]]
- compares → [[ad-ldap-corp]]
- depends_on → [[vpn-gateway-corp]]
- see_also → [[vpn-authentication-flow]]

## Sources

1. [VPN Troubleshooting SOP (Chinese)](examples/scn_ticket_summary_zh/kb/sop_vpn_zh.md:42) — RADIUS / AD LDAP ports and troubleshooting path

## Changelog

- v1.0.0 (2026-05-01): initial; from doc_88a277cf
