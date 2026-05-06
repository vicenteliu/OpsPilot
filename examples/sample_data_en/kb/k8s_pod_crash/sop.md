---
doc_id: doc_a1b2c3d4
title: Kubernetes Pod Crash Troubleshooting SOP
valid_from: 2026-01-15
source_authority: official
---

# Kubernetes Pod Crash Troubleshooting SOP

> Scope: Kubernetes 1.27+. Covers CrashLoopBackOff, OOMKilled, and ImagePullBackOff. Does not cover node-level failures.

## 1. Symptom Classification

Use `kubectl describe pod <name>` and `kubectl logs <name> --previous` to identify the failure category:

| Symptom | Exit Code / Status | Likely Root Cause |
|---|---|---|
| CrashLoopBackOff | Non-zero exit | App error, missing env var, bad liveness probe |
| OOMKilled | Exit 137 | Memory limit too low or memory leak |
| ImagePullBackOff | ErrImagePull | Wrong tag, registry auth failure, network issue |
| Pending / Unschedulable | — | Insufficient cluster resources, node selector mismatch |

## 2. Troubleshooting Steps

### 2.1 CrashLoopBackOff

1. **Fetch previous logs**: `kubectl logs <pod> --previous -n <namespace>` — look for the last error line.
2. **Check env vars**: `kubectl get pod <pod> -o jsonpath='{.spec.containers[*].env}'` — verify all required keys are present.
3. **Probe misconfiguration**: `kubectl describe pod <pod>` → check liveness/readiness probe settings. A probe that fires before the app is ready will restart the pod immediately.
4. **Resource limits**: If `OOMKilled` appears in logs, increase `resources.limits.memory` by 2× and redeploy.
5. **Image tag**: Confirm the image SHA matches the intended release: `kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[*].imageID}'`.

**Escalation criteria**: CrashLoopBackOff persists after log inspection + env var correction → escalate to Platform Team with `kubectl describe pod` output.

### 2.2 ImagePullBackOff

1. **Verify registry credentials**: `kubectl get secret regcred -o yaml` — check `imagePullSecrets` in the pod spec.
2. **Check image tag existence**: `docker manifest inspect <image>:<tag>` from a node with registry access.
3. **Network reachability**: From a node, `curl -I https://<registry-host>/v2/` — expect HTTP 200 or 401.

## 3. Escalation Policy

| Condition | Escalation Target |
|---|---|
| OOMKilled, limit already doubled | Platform Team (capacity review) |
| ImagePullBackOff, registry credentials correct | Security Team (registry ACL audit) |
| CrashLoopBackOff, app logs show missing secrets | Secrets Management Team |
| Unschedulable for > 15 min | Platform Team (cluster autoscaler check) |
