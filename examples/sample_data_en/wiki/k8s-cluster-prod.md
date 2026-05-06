---
page_id: "wpg_a1b2c3d4"
slug: "k8s-cluster-prod"
kind: "entity"
title: "Production Kubernetes Cluster"
summary: "Primary production Kubernetes cluster (v1.29) running all customer-facing services; managed via EKS with Karpenter autoscaling."
namespace: "opspilot:public-kb"
classification: "internal"
language: "en"
version: "1.0.0"
created_at: "2026-05-06T10:00:00Z"
updated_at: "2026-05-06T10:00:00Z"

tags: ["kubernetes", "eks", "platform", "production", "infrastructure"]
aliases: ["prod-k8s", "EKS prod cluster", "Kubernetes production"]

derived_from:
  sources:
    - kind: "kb_document"
      ref: "doc_a1b2c3d4"
      sha256: "sha256:a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4a1b2c3d4"
      line_start: 8
      line_end: 48
  parent_pages: []

outbound_links: ["wpg_e5f6a7b8"]
inbound_link_count: 0

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

extensions:
  entity:
    related_entities:
      - "aws-iam-prod-role"
      - "db-connection-pool-prod"
    related_concepts:
      - "pod-failure-taxonomy"
      - "oncall-escalation-matrix"
---

# Production Kubernetes Cluster

## What is it

The primary EKS cluster (`prod-us-east-1`) running all customer-facing microservices. Kubernetes v1.29, 12 node groups managed by Karpenter, cross-AZ spread across us-east-1a/b/c.

## Key facts

- **Version**: Kubernetes 1.29 (EKS managed)
- **Autoscaler**: Karpenter — nodes provisioned within 30–60 s of pending pods
- **CNI**: AWS VPC CNI; pod CIDR 10.100.0.0/16
- **Ingress**: NGINX Ingress Controller v1.10 behind AWS NLB
- **Monitoring**: Prometheus + Grafana; alerts route to `#oncall-platform` via PagerDuty `svc-platform-oncall`
- **Common failure modes**: CrashLoopBackOff (app misconfiguration), OOMKilled (memory under-provisioned), ImagePullBackOff (registry auth)

## Diagnostics quick start

```bash
# Check pod status
kubectl get pods -n <namespace> --field-selector=status.phase!=Running

# Describe a crashing pod
kubectl describe pod <pod-name> -n <namespace>

# Fetch previous container logs
kubectl logs <pod-name> -n <namespace> --previous

# Node pressure
kubectl top nodes
kubectl describe node <node> | grep -A5 "Conditions:"
```

## Escalation

See [[pod-failure-taxonomy]] for symptom → root-cause mapping.  
Escalate to Platform Team via `svc-platform-oncall` if CrashLoopBackOff persists after basic remediation.

## Related

- see_also → [[pod-failure-taxonomy]]: failure classification guide
- depends_on → [[oncall-escalation-matrix]]: severity tiers and paging contacts

## Sources

1. [Kubernetes Pod Crash Troubleshooting SOP](examples/sample_data_en/kb/k8s_pod_crash/sop.md:8-48)

## Changelog

- v1.0.0 (2026-05-06): initial; derived from doc_a1b2c3d4
