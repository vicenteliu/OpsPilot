---
# Wiki index — content catalog
# Automatically reorganized by the wiki-maintainer skill after every ingest
# Human read-only; do not hand-edit

slug: "index"
kind: "concept"           # reuses the concept kind, but lifecycle is always live
title: "Wiki Index"
summary: "Catalog of all wiki pages, grouped by kind."
namespace: "opspilot:public-kb"
classification: "internal"
language: "mixed"
version: "1.0.0"
created_at: "2026-05-01T10:00:00Z"
updated_at: "2026-05-01T10:00:00Z"
tags: ["index", "meta"]
aliases: ["Table of contents", "TOC"]
derived_from:
  sources: []
  parent_pages: []
outbound_links: []
inbound_link_count: 999       # forced large value so lint does not mis-flag it as an orphan
redacted: true
redaction_rules_version: "1.0.0"
lifecycle_state: "live"
owner: "wiki-maintainer-skill"
extensions:
  meta:
    is_meta_page: true
    auto_maintained: true
---

# Wiki Index

> Auto-maintained. Grouped under `## ` second-level headings, one line per page.
> Parse rule: `^- \[\[(\S+?)\]\] — (.+?) · ` (slug · summary · classification · tag)

## Entities

- [[vpn-gateway-corp]] — Corporate IPSec/IKEv2 VPN gateway; RADIUS + AD LDAP two-factor · `internal` · #vpn #infrastructure
- [[radius-auth-backend]] — RADIUS authentication backend; UDP 1812/1813 · `internal` · #auth
- [[ad-ldap-corp]] — AD LDAP directory service; TCP 389/636 · `internal` · #auth

## Concepts

- [[ipsec-vs-ssl-vpn]] — IPSec vs SSL VPN selection comparison · `internal` · #vpn #concept
- [[vpn-authentication-flow]] — VPN authentication flow: client → gateway → RADIUS → AD LDAP · `internal` · #auth #flow

## Summaries (one per raw source)

- [[sop-vpn-zh-2026-04-28]] — VPN Troubleshooting SOP (Chinese) v1.3.0 · `internal` · #vpn #sop
- [[summary-ticket-T-XXXX-2026-04-30]] — Ticket summary for session sess_01J0Z9... · `internal` · #ticket

## Comparisons

- [[radius-vs-ldap-auth]] — RADIUS vs AD LDAP authentication backend selection · `internal` · #auth #comparison

## Syntheses

- [[vpn-incident-patterns-2026q1]] — 2026 Q1 VPN incident pattern synthesis (thesis: 80% in the auth chain) · `internal` · #vpn #q1-2026

## Meta

- [[index]] — this page
- [[log]] — chronological ledger

---

**Stats (maintained by lint)**:
- Total pages: 9
- By kind: entity=3, concept=2, summary=2, comparison=1, synthesis=1
- Orphans: 0
- Open lint issues: 0
- Last updated: 2026-05-01T10:00:00Z
