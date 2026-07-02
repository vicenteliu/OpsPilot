---
# Summary page — summary of a single source (maps directly to 1 raw source)
# Equivalent to schemas/wiki-page.schema.json (kind=summary)

page_id: "wpg_22222222"
slug: "sop-vpn-zh-2026-04-28"
kind: "summary"
title: "Source Summary: VPN Troubleshooting SOP (Chinese) — v1.3.0 / 2026-04-28"
summary: "The source SOP covers the IPSec/IKEv2 VPN symptom classification table, auth-error troubleshooting steps, tunnel troubleshooting, and L2 escalation criteria."
namespace: "opspilot:public-kb"
classification: "internal"
language: "zh-CN"
version: "1.0.0"
created_at: "2026-05-01T10:00:00Z"
updated_at: "2026-05-01T10:00:00Z"

tags: ["summary", "vpn", "sop", "L1"]
aliases: []

derived_from:
  sources:
    - kind: "kb_document"
      ref: "doc_88a277cf"
      sha256: "sha256:88a277cf857f9fdee36c4b8272b40bdfa121e3a9526956f9f21cc7198f3e456d"
      line_start: null
      line_end: null
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
  summary:
    source_doc_id: "doc_88a277cf"
    source_uri: null
---

# Source Summary: VPN Troubleshooting SOP (Chinese) v1.3.0

## TL;DR

The L1 troubleshooting SOP for the corporate IPSec/IKEv2 VPN. It classifies symptoms into three categories (auth failure / tunnel fails to establish / extremely slow) and defines keywords and a troubleshooting path for each. **Simultaneous auth failures across multiple users → the server-side auth chain** is the SOP's core thesis.

## Key claims

1. Simultaneous auth failures across multiple users are almost always a server-side problem (not a single endpoint) — driving the troubleshooting order: logs → backend health → console test login → time sync
2. Broken NAT-T causes ESP packets to be dropped → the tunnel cannot establish; test UDP 500/4500 reachability
3. MTU rule of thumb: step down gradually from 1400 → 1200; common when traversing NAT
4. Criteria for escalating to the L2 network team: multiple users affected + no auth records in server logs

## Implications for our wiki

- Created the [[vpn-gateway-corp]] entity page recording the main facts
- Created the [[ipsec-vs-ssl-vpn]] concept page recording the protocol selection
- **Missing**: entity / concept pages such as [[ssl-vpn-gateway-corp]], [[vpn-authentication-flow]], [[radius-auth-backend]] — queued in the lint missing_concept_page queue
- Aligned with historical pages: this SOP does not conflict with existing entity facts

## Cross-links

- describes → [[vpn-gateway-corp]]
- describes → [[ipsec-vs-ssl-vpn]]

## Sources

1. [VPN Troubleshooting SOP (Chinese)](examples/scn_ticket_summary_zh/kb/sop_vpn_zh.md:1-63) — full text

## Changelog

- v1.0.0 (2026-05-01): initial; from doc_88a277cf
