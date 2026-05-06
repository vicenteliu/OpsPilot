---
page_id: "wpg_e5f6a7b8"
slug: "pod-failure-taxonomy"
kind: "concept"
title: "Kubernetes Pod Failure Taxonomy"
summary: "Structured classification of Kubernetes pod failure modes by exit code, status, and likely root cause; maps symptoms to first-response actions."
namespace: "opspilot:public-kb"
classification: "internal"
language: "en"
version: "1.0.0"
created_at: "2026-05-06T10:00:00Z"
updated_at: "2026-05-06T10:00:00Z"

tags: ["kubernetes", "k8s", "troubleshooting", "crashloopbackoff", "oomkilled", "concept"]
aliases: ["pod crash taxonomy", "k8s failure modes", "CrashLoopBackOff causes"]

derived_from:
  sources:
    - kind: "kb_document"
      ref: "doc_a1b2c3d4"
      sha256: "sha256:a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4"
      line_start: 8
      line_end: 22
  parent_pages: []

outbound_links: ["wpg_a1b2c3d4"]
inbound_link_count: 1

redacted: true
redaction_rules_version: "1.0.0"

lifecycle_state: "live"
owner: "platform-team@example.com"
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

# Kubernetes Pod Failure Taxonomy

## Overview

Pod failures in Kubernetes fall into four canonical categories. Correct classification in the first 60 seconds determines which team to page and which runbook to follow.

## Failure Map

| Status / Exit Code | Category | First Check | Owner |
|---|---|---|---|
| `CrashLoopBackOff` + exit 1 | App crash | `kubectl logs --previous` | App team |
| `OOMKilled` / exit 137 | Memory exhaustion | `kubectl top pod`, check `resources.limits.memory` | App + Platform |
| `ImagePullBackOff` / `ErrImagePull` | Registry failure | Check `imagePullSecrets`, image tag, network | Platform |
| `Pending` / `Unschedulable` | Scheduling failure | `kubectl describe pod` → Events section | Platform |

## CrashLoopBackOff Deep Dive

The most common failure. Back-off timer doubles on each restart (10 s → 20 s → 40 s → max 5 min). Diagnosis order:

1. Previous logs (`--previous`) — most errors are self-explanatory
2. Missing env vars — check `ConfigMap` and `Secret` mounts
3. Liveness probe fires too early — add `initialDelaySeconds`
4. Memory limit hit → see OOMKilled below

## OOMKilled

Exit code 137 = SIGKILL from the kernel OOM killer. Always caused by RSS exceeding `resources.limits.memory`.

- Short-term: double the limit
- Long-term: profile the application with `pprof` or heap dump; fix the leak

## ImagePullBackOff

Registry auth fails silently. Checklist:

- `imagePullSecrets` present in pod spec AND secret exists in the namespace
- Image tag exists in registry (`docker manifest inspect`)
- Registry endpoint reachable from nodes (`curl -I https://<registry>/v2/`)

## Related

- entity → [[k8s-cluster-prod]]: the cluster this taxonomy applies to
- see_also → [[oncall-escalation-matrix]]: when to page Platform vs App team

## Sources

1. [Kubernetes Pod Crash Troubleshooting SOP](examples/sample_data_en/kb/k8s_pod_crash/sop.md:8-22)

## Changelog

- v1.0.0 (2026-05-06): initial; derived from doc_a1b2c3d4
