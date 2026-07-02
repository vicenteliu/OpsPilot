---
# Synthesis page — cross-source synthesis (the most valuable; derives a thesis from ≥2 raw sources)
# Equivalent to schemas/wiki-page.schema.json (kind=synthesis)

page_id: "wpg_44444444"
slug: "vpn-incident-patterns-2026q1"
kind: "synthesis"
title: "VPN Incident Patterns Q1 2026"
summary: "Synthesis of 12 L1 tickets + the SOP + 1 RCA document: multi-user auth failures dominate; multiple sources point to server-side time sync and insufficient RADIUS health monitoring."
namespace: "opspilot:public-kb"
classification: "internal"
language: "zh-CN"
version: "1.0.0"
created_at: "2026-05-01T10:00:00Z"
updated_at: "2026-05-01T10:00:00Z"

tags: ["synthesis", "vpn", "incident", "Q1-2026"]
aliases: ["VPN Q1 synthesis"]

derived_from:
  sources:
    - kind: "kb_document"
      ref: "doc_88a277cf"
      sha256: "sha256:88a277cf857f9fdee36c4b8272b40bdfa121e3a9526956f9f21cc7198f3e456d"
      line_start: null
      line_end: null
    - kind: "session"
      ref: "sess_01J0Z9ZQXK7M6P3F0XK5K7C5K0"
      sha256: null
      line_start: null
      line_end: null
    - kind: "kb_document"
      ref: "doc_aaaaaaaa"     # hypothetical: another RCA report (placeholder example)
      sha256: null
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
  synthesis:
    thesis: "In 2026 Q1, 80% of VPN incidents were concentrated in the auth chain; root causes center on NTP drift + the RADIUS single point of failure. Fixing these two is expected to eliminate most incidents."
    evidence_count: 5
    counter_evidence_count: 1
---

# VPN Incident Patterns: 2026 Q1

## Thesis

> **In 2026 Q1, 80% of the company's VPN incidents were concentrated in the auth chain; root causes center on NTP drift + the RADIUS single point of failure. Fixing these two is expected to eliminate most incidents.**

## Evidence

1. **Multi-user auth failures = a server-side problem** (from [[sop-vpn-zh-2026-04-28]] / SOP §2.1) — not a single endpoint
2. **2026-04-30 ticket** ([[summary-ticket-T-XXXX-2026-04-30]], session sess_01J0Z9...): a typical multi-user VPN auth failure case, confirmed as a server-side auth problem
3. **March RCA report** (`doc_aaaaaaaa`, placeholder): the previous large-scale incident was caused by a RADIUS HA failover problem (to be filled in after ingest)
4. **Client log keyword distribution**: 9 of 12 tickets contain `peer authentication failed` (75%)
5. **Time sync is listed as troubleshooting step 4 in the SOP** — ticket data shows ≥3 incidents whose actual root cause was time-sync drift

## Counter-evidence

1. 1 ticket (8%) was actually NAT-T packets dropped by an intermediate ISP device — inconsistent with the thesis; indicates the thesis should be scoped to "recurring / multi-user" incidents

## Implications

- **Recommended investments**:
  - RADIUS HA health monitoring + automated failover verification (the single point of failure is the thesis's second item) — added to [[radius-auth-backend]] as a todo
  - NTP sync alerting across the VPN gateway, RADIUS, and AD LDAP (the thesis's first item) — see [[vpn-gateway-corp]]
- **Not recommended**: blindly introducing an SSL VPN backup entry point — not directly related to the thesis (see the [[ipsec-vs-ssl-vpn]] decision matrix)

## Gaps

- No full-quarter Q1 ticket database; current evidence comes from sampling
- No precise quantification yet of NTP drift → auth failures; 1-2 more relevant sources need to be ingested

## Cross-links

- extends → [[sop-vpn-zh-2026-04-28]]
- describes → [[vpn-gateway-corp]]
- describes → [[radius-auth-backend]]
- compares → [[ipsec-vs-ssl-vpn]]
- see_also → [[summary-ticket-T-XXXX-2026-04-30]]

## Sources

1. [VPN Troubleshooting SOP (Chinese)](examples/scn_ticket_summary_zh/kb/sop_vpn_zh.md:37-46) — auth-error troubleshooting steps
2. [Session sess_01J0Z9ZQXK7M6P3F0XK5K7C5K0](examples/scn_ticket_summary_zh/session/) — a representative single-ticket session
3. doc_aaaaaaaa (placeholder pending ingest) — March RCA report

## Changelog

- v1.0.0 (2026-05-01): initial synthesis from 3 sources
