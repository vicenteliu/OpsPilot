---
doc_id: doc_d7e8f9a0
title: On-call Incident Escalation Runbook
valid_from: 2026-03-15
source_authority: official
---

# On-call Incident Escalation Runbook

> Scope: All production incidents. Defines severity tiers, escalation targets, and communication SLAs. Supersedes the 2025 escalation matrix.

## 1. Severity Tiers and Escalation Matrix

Classify the incident before paging anyone. Misclassification wastes responder time.

| Severity | Definition | Response SLA | Escalation Target |
|---|---|---|---|
| P0 | Full production outage; > 50% users impacted | Page immediately | On-call Engineer + Engineering Manager + VP Engineering |
| P1 | Partial outage or severe degradation; core feature broken | 15 min | On-call Engineer + Team Lead |
| P2 | Non-critical feature degraded; workaround exists | 60 min | On-call Engineer |
| P3 | Minor bug; no user impact | Next business day | Ticket only |

**Escalation triggers** (upgrade severity if any apply):
- Duration > 2× the response SLA with no mitigation in place → escalate one tier
- Customer-reported (external) before internal detection → P1 minimum
- Data loss or data corruption suspected → P0 regardless of scope

### Escalation Contacts

| Team | PagerDuty Service | Slack Channel |
|---|---|---|
| Platform / Infra | `svc-platform-oncall` | `#oncall-platform` |
| Backend / API | `svc-backend-oncall` | `#oncall-backend` |
| Security | `svc-security-oncall` | `#oncall-security` |
| Database | `svc-dba-oncall` | `#oncall-dba` |

## 2. Communication Templates

Use these templates verbatim. Do not improvise during active incidents.

### 2.1 Initial Alert (post within 5 min of detection)

```
[INCIDENT STARTED] <Severity> — <Brief title>
- Started: <ISO timestamp>
- Impact: <What is broken / who is affected>
- Current status: Investigating
- Commander: <Your name>
- Bridge: <Zoom link>
```

### 2.2 Status Update (every 15 min for P0/P1)

```
[UPDATE <HH:MM>] <Severity> — <Title>
- Progress: <What has been tried / found>
- Current hypothesis: <Root cause theory>
- Next action: <Specific next step + owner + ETA>
- ETA to resolution: <estimated or "unknown">
```

### 2.3 Resolution Notice

```
[RESOLVED <HH:MM>] <Severity> — <Title>
- Duration: <start> → <end> (<total minutes>)
- Root cause: <one sentence>
- Fix applied: <what was changed>
- Follow-up: PIR scheduled for <date> — owner: <name>
```

**Escalation criteria**: No mitigation after 30 min on a P1 → auto-escalate to P0 and page Engineering Manager.
