---
# Entity page — a single object (system, tool, team, person, product)
# Equivalent to schemas/wiki-page.schema.json (kind=entity)

page_id: "wpg_00000000"           # wpg_<sha8>; computed at runtime
slug: "vpn-gateway-corp"
kind: "entity"
title: "Corporate VPN Gateway"
summary: "Corporate IPSec/IKEv2 VPN gateway; handles employee remote access; backend uses RADIUS + AD LDAP two-factor."
namespace: "opspilot:public-kb"
classification: "internal"
language: "zh-CN"
version: "1.0.0"
created_at: "2026-05-01T10:00:00Z"
updated_at: "2026-05-01T10:00:00Z"

tags: ["vpn", "ipsec", "ikev2", "infrastructure"]
aliases: ["VPN gateway", "Corporate VPN", "IPSec gateway"]

derived_from:
  sources:
    - kind: "kb_document"
      ref: "doc_88a277cf"
      sha256: "sha256:88a277cf857f9fdee36c4b8272b40bdfa121e3a9526956f9f21cc7198f3e456d"
      line_start: 21
      line_end: 33
  parent_pages: []

outbound_links: []                # machine-maintained
inbound_link_count: 0             # back-filled by lint

redacted: true
redaction_rules_version: "1.0.0"

lifecycle_state: "live"
owner: "vicente@example.com"
collaborators: []

kb_registration:
  kb_doc_id: null                 # back-filled by the wiki→KB registration flow after entering live
  registered_at: null
  embedding_model: null
  chunk_count: null

lint_state:
  last_linted_at: null
  open_issue_ids: []

extensions:
  entity:
    related_entities:
      - "radius-auth-backend"
      - "ad-ldap-corp"
    related_concepts:
      - "ipsec-vs-ssl-vpn"
      - "vpn-authentication-flow"
---

# Corporate VPN Gateway

## What is it

The primary entry point for corporate remote access; based on IPSec / IKEv2, exposing UDP 500 (IKE) + UDP 4500 (NAT-T).

## Key facts

- **Protocol**: IKEv2 over UDP; ESP (IP protocol 50) encapsulated via NAT-T
- **Auth backend**: RADIUS (ports 1812/1813) → AD LDAP (389/636) two-factor
- **Clients**: strongSwan / Windows built-in VPN / macOS built-in VPN
- **Common symptom keywords**: `authentication failed`, `peer auth failed`, `IKE_SA_INIT failed`, `IKE timeout`
- **Simultaneous auth failures across multiple users → a server-side auth-chain problem** (not a single endpoint) — see [[ipsec-vs-ssl-vpn]]

## Diagnostics quick start

1. Client logs: `grep -E "auth|fail" vpn-client.log`
2. Server health: RADIUS / AD LDAP ports reachable
3. Time sync: `chronyc tracking` / `ntpq -p`; drift > 30s raises errors

## Related

- describes → [[radius-auth-backend]]: concrete implementation of the RADIUS backend
- describes → [[ad-ldap-corp]]: the AD LDAP service
- depends_on → [[ipsec-vs-ssl-vpn]]: protocol selection background

## Cross-links

- describes → [[radius-auth-backend]]: upstream of the auth chain
- describes → [[ad-ldap-corp]]: upstream of the auth chain
- see_also → [[ipsec-vs-ssl-vpn]]
- see_also → [[vpn-incident-patterns-2026q1]]

## Sources

1. [VPN Troubleshooting SOP (Chinese)](examples/scn_ticket_summary_zh/kb/sop_vpn_zh.md:21-33) — symptom classification table and protocol scope
2. [VPN Troubleshooting SOP (Chinese)](examples/scn_ticket_summary_zh/kb/sop_vpn_zh.md:37-46) — auth-error troubleshooting steps

## Changelog

- v1.0.0 (2026-05-01): initial; from doc_88a277cf
