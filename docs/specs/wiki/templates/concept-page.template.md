---
# Concept page — an abstract concept or topic
# Equivalent to schemas/wiki-page.schema.json (kind=concept)

page_id: "wpg_11111111"
slug: "ipsec-vs-ssl-vpn"
kind: "concept"
title: "IPSec vs SSL VPN: When to Choose Which"
summary: "IPSec operates at the network layer (L3), SSL VPN at the application layer (L7/TLS); they trade off in performance, NAT traversal, client complexity, and operational cost."
namespace: "opspilot:public-kb"
classification: "internal"
language: "zh-CN"
version: "1.0.0"
created_at: "2026-05-01T10:00:00Z"
updated_at: "2026-05-01T10:00:00Z"

tags: ["vpn", "ipsec", "ssl", "concept"]
aliases: ["VPN selection", "L3 VPN vs L7 VPN"]

derived_from:
  sources:
    - kind: "kb_document"
      ref: "doc_88a277cf"
      sha256: "sha256:88a277cf857f9fdee36c4b8272b40bdfa121e3a9526956f9f21cc7198f3e456d"
      line_start: 23
      line_end: 23
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

extensions: {}
---

# IPSec vs SSL VPN

## Definition

The two mainstream technical approaches to VPN (Virtual Private Network):

- **IPSec**: encrypts and encapsulates at the IP layer, typically using IKEv2 for key negotiation; natively supports any L3+ protocol; clients usually require OS-level support.
- **SSL VPN**: runs a proprietary application protocol on top of TLS; uses port 443, with **strong firewall traversal**; the client is usually a browser or a lightweight agent.

## Why it matters

- **Different failure modes**: IPSec typically fails at IKE negotiation / NAT-T / time sync; SSL VPN typically fails at certificates / browser compatibility / application proxy routing
- **Different operational boundaries**: the IPSec gateway and the application-layer proxy are maintained by different teams; when both coexist in a company, [[vpn-incident-patterns-2026q1]] shows 80% of tickets first require determining which one is involved
- **Different client policies**: IPSec carries all traffic; SSL VPN usually split-tunnels, protecting only specific applications

## Examples in our environment

- Primary entry point: [[vpn-gateway-corp]] — IPSec / IKEv2
- Backup entry point: SSL VPN (for BYOD / third-party collaboration) — entity page pending

## Trade-offs

| Dimension | IPSec | SSL VPN |
|---|---|---|
| NAT/firewall traversal | Fair (needs NAT-T; UDP 500/4500 may be blocked) | Strong (443 / TCP) |
| Performance | High | Medium |
| Client complexity | High (OS integration / strongSwan / config files) | Low (browser / lightweight agent) |
| Full traffic vs split-tunnel | Usually full traffic | Split-tunnel friendly |
| Operational ownership | Network team | Application / access team |

For a more detailed comparison see [[ipsec-vs-ssl-vpn-decision-matrix]] (synthesis page, to be generated).

## Cross-links

- compares → [[vpn-gateway-corp]] (IPSec primary entry point)
- see_also → [[vpn-authentication-flow]]
- see_also → [[ssl-vpn-gateway-corp]] (entity page to be generated)

## Sources

1. [VPN Troubleshooting SOP (Chinese)](examples/scn_ticket_summary_zh/kb/sop_vpn_zh.md:23) — the Scope section's definition of protocol coverage

## Changelog

- v1.0.0 (2026-05-01): initial; from doc_88a277cf
