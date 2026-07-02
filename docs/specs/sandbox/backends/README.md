# Sandbox Backends — Backend Selection Guide

> Spec only — capability comparison, selection guidance, and rollout notes. This document contains **no** runtime implementation.

## TL;DR
- **Default starting point**: Docker (L1)
- **Hardened production pilot**: Docker hardened (L2, adds seccomp + cap-drop + RO rootfs)
- **Multi-tenant / external input**: gVisor
- **Strong isolation / microVM**: Firecracker or Kata
- **Production canary across network segments**: Remote VM

## Capability matrix

| Dimension | Docker (L1) | Docker hardened (L2) | gVisor | Firecracker / Kata | Remote VM |
|---|---|---|---|---|---|
| Isolation strength | Medium | Medium-high | High (user-space kernel) | Very high (microVM) | Environment-dependent |
| Startup overhead | Sub-second | Sub-second | Medium | ~125 ms | Seconds to minutes |
| Complexity | Low | Medium | Medium | Medium-high | High |
| Linux host requirements | Docker engine | + seccomp/AppArmor | + runsc | + KVM | Remote |
| macOS host experience | Good (Docker Desktop) | Same as L1 | Requires a Linux VM | Not possible (no KVM) | Good |
| Best-fit scenarios | Dev machines / self-hosted pilots | Small production traffic on internal networks | Multi-tenant / handling suspicious input | Strong compliance / high-density multi-tenancy | Production canary |
| Known weaknesses | Namespaces share the kernel | Same performance as L1 | Some syscalls incompatible | Longer deployment chain | Network latency, cost |

## 1. Docker (L1) — Default

Suitable for: development, pilots, self-hosting, internal networks, individual use.

Key points:
- Recommended images: `debian:stable-slim` or `ubuntu:24.04` + only the necessary tools installed
- Key flags (recommended defaults):
  ```
  --rm
  --read-only
  --tmpfs /tmp:rw,nosuid,nodev,size=64m
  --cap-drop=ALL
  --network=none
  --pids-limit=128
  --memory=512m
  --cpus=1
  --security-opt=no-new-privileges
  -u 65534:65534          # nobody:nogroup
  ```
- Do not mount `~/.ssh`, `~/.aws`, `~/.kube`, `/var/run/docker.sock`

Risks:
- Shares the host kernel; a kernel-level 0day can still escape
- Runs as root by default; always use `-u` to switch to an unprivileged UID

## 2. Docker hardened (L2) — Hardened mode

On top of L1, add:
- `--security-opt seccomp=policies/seccomp.template.json`
- `--security-opt apparmor=opspilot-default` (requires an AppArmor profile configured on the host)
- At the image level: remove `setuid`/`setgid` binaries; minimal dependencies
- Kernel capabilities: add only when necessary (default `--cap-drop=ALL`)

Suitable for: extending internal-network pilots to part of production; handling semi-trusted input.

## 3. gVisor

> Docs: https://gvisor.dev/docs/

Positioning: a user-space kernel (runsc) that intercepts syscalls, raising "container isolation" to near-VM strength.

Suitable for:
- Multi-tenant shared hosts
- Handling external/suspicious input (e.g. customer-uploaded logs)
- When you do not want to place all your trust in the Linux kernel

Key points:
- Docker integration: `--runtime=runsc`
- Performance: CPU/IO overhead (on the order of 10–30%, workload-dependent)
- Compatibility: a small number of syscalls are unsupported (e.g. some `io_uring` paths); run fixture detection in staging first

Deployment checklist (high level):
1. Install `runsc` on the host
2. Register the runtime in `/etc/docker/daemon.json`
3. Test: `docker run --runtime=runsc -it debian:stable-slim uname -a`

> **Implemented (L3)**: OpsPilot's gVisor backend lives in `src/opspilot/sandbox/docker_l3.py`
> (see [ADR-0009](../../../adr/0009-sandbox-l3-gvisor-over-firecracker.md) for the selection decision).
> Usage: `opspilot sandbox run --level l3 <action.yaml>`. When `runsc` is not registered,
> it **fails closed** (no fallback to L2).

## 4. Firecracker / Kata Containers

> Docs: https://firecracker-microvm.github.io/  https://katacontainers.io/

Positioning: microVMs, ~125 ms startup, strong hardware isolation (relies on KVM).

Suitable for:
- Strict compliance requirements (finance, government)
- High-density multi-tenancy
- Existing Kubernetes + Kata pipelines

Key points:
- Required: Linux host + KVM (`/dev/kvm`)
- Usually unavailable on macOS / under nested virtualization (small cloud instance types)
- Deployment chain: Firecracker → containerd shim → Kubernetes (CRI); building it yourself is heavy — evaluate Kata first
- Resource overhead: roughly 5 MiB of baseline memory per microVM

## 5. Remote VM — Remote isolated VM

Positioning: run the sandbox in a separate VM/account to maximize blast radius isolation.

Suitable for:
- Production canary (across network segments / accounts)
- Needing to reach internal networks / specific network locations
- Multiple teams sharing OpsPilot while keeping audits isolated

Key points:
- Control plane (OpsPilot) ↔ data plane (remote VM) communicate over an mTLS channel
- Credentials: the remote VM stores no OpsPilot primary-account credentials; short-lived credentials are issued per action
- Cost: always-on VM vs on-demand start/stop — on-demand has high startup latency, always-on costs more; weigh the trade-off

## Decision tree

```
Local machine / small-team pilot only? ──▶ Yes ──▶ Docker (L1)
        │
        No
        ▼
Handling external / suspicious input? ──▶ Yes ──▶ gVisor or Firecracker
        │
        No
        ▼
Production across network segments? ──▶ Yes ──▶ Remote VM (+ inner Docker hardened)
        │
        No
        ▼
Very high compliance requirements? ──▶ Yes ──▶ Firecracker / Kata
        │
        No ──▶ Docker hardened (L2)
```

## Backend abstraction

Every backend implementation must satisfy the following contract (implementation details are out of scope for this directory):

```
backend.run(action_request, policy) -> action_record
backend.dry_run(action_request, policy) -> dry_run_record
backend.cancel(action_id) -> ok
backend.health() -> {ok|degraded|down, details}
```

- `action_record` / `dry_run_record` fields must map back to `tool_result` in `session/schemas/trace-event.schema.json`
- Every backend must support semantics equivalent to `--network=none`

## Backup & rollback notes

- Switching the default backend is a **main-path** change; run the full harness in staging before changing
- Rollback path: keep the previous backend rollback-ready for 6 weeks; tag the image and pin the docker-compose version before the change
- gVisor / Firecracker upgrades: dry-run the fixtures first; incompatible syscalls fail with explicit errors
