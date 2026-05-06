---
page_id: "wpg_d7e8f9a0"
slug: "oncall-escalation-matrix"
kind: "synthesis"
title: "On-call Escalation Matrix"
summary: "Synthesized escalation decision guide: maps incident severity (P0–P3) to paging targets, SLAs, and communication templates for all production teams."
namespace: "opspilot:public-kb"
classification: "internal"
language: "en"
version: "1.0.0"
created_at: "2026-05-06T10:00:00Z"
updated_at: "2026-05-06T10:00:00Z"

tags: ["oncall", "escalation", "incident", "sre", "P0", "P1", "communication"]
aliases: ["escalation matrix", "incident severity tiers", "on-call runbook"]

derived_from:
  sources:
    - kind: "kb_document"
      ref: "doc_d7e8f9a0"
      sha256: "sha256:d7e8f9a0d7e8f9a0d7e8f9a0d7e8f9a0d7e8f9a0d7e8f9a0d7e8f9a0d7e8f9a0"
      line_start: 8
      line_end: 72
  parent_pages: []

outbound_links: ["wpg_a1b2c3d4", "wpg_f3a4b5c6"]
inbound_link_count: 3

redacted: true
redaction_rules_version: "1.0.0"

lifecycle_state: "live"
owner: "sre-team@example.com"
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
    thesis: "Consistent severity classification and scripted communication are the two highest-leverage practices for reducing MTTR in production incidents."
    evidence_count: 4
    counter_evidence_count: 0
---

# On-call Escalation Matrix

## Thesis

Consistent severity classification and scripted communication are the two highest-leverage practices for reducing MTTR in production incidents. This page synthesises the escalation runbook (`doc_d7e8f9a0`) into a single actionable reference.

## Severity → Action Map

| Severity | Trigger | SLA | Page | Comms cadence |
|---|---|---|---|---|
| **P0** | > 50% users, full outage | Immediate | On-call + EM + VP Eng | Every 15 min |
| **P1** | Core feature broken, partial outage | 15 min | On-call + Team Lead | Every 15 min |
| **P2** | Degraded, workaround exists | 60 min | On-call | Every 60 min |
| **P3** | No user impact | Next biz day | Ticket only | N/A |

**Auto-escalation rule**: If no mitigation is in place after 2× the SLA, bump one severity tier.

## Paging Contacts

| Domain | PagerDuty | Slack |
|---|---|---|
| Platform / K8s | `svc-platform-oncall` | `#oncall-platform` |
| Backend / API | `svc-backend-oncall` | `#oncall-backend` |
| Security / TLS | `svc-security-oncall` | `#oncall-security` |
| Database | `svc-dba-oncall` | `#oncall-dba` |

## Communication Discipline

Three mandatory messages; use the runbook templates verbatim:

1. **Initial alert** — within 5 min of detection (severity, impact, commander, bridge link)
2. **Status update** — every 15 min for P0/P1 (progress, hypothesis, next action, ETA)
3. **Resolution notice** — immediately after fix (duration, root cause, follow-up date)

## Cross-Domain Escalation Examples

- K8s OOMKilled, limit already doubled → Platform Team capacity review (`svc-platform-oncall`)
- AWS IAM SCP-level deny → AWS Account Owner (outside standard PagerDuty)
- TLS key compromised → Security Team within 1 h (`svc-security-oncall`)
- DB `max_connections` at system limit → DBA Team (`svc-dba-oncall`)

## Related

- see_also → [[k8s-cluster-prod]]: K8s-specific escalation paths
- see_also → [[tls-cert-lifecycle]]: TLS emergency rotation is always a P0

## Sources

1. [On-call Incident Escalation Runbook](examples/sample_data_en/kb/oncall_escalation/runbook.md:8-72)

## Changelog

- v1.0.0 (2026-05-06): initial; synthesised from doc_d7e8f9a0
