# ADR-0009: Sandbox L3 is gVisor (runsc), not Firecracker/Kata

**Status**: Accepted
**Date**: 2026-06-06
**Stage**: 5 (productionization)

## Context

docs/zh/design/STAGES.md §7.5 lists "sandbox L3 (one of gVisor / Firecracker / Kata; as needed)" as an
optional Stage 5 hardening item. L2 (`sandbox/docker_l2.py`) is a Docker
*hardened* container: read-only rootfs, `--cap-drop=ALL`, `no-new-privileges`,
a custom seccomp profile, and resource/pid limits. Its residual risk is the one
named in `docs/specs/sandbox/backends/README.md`: the container still shares the host Linux
kernel, so a kernel-level 0-day can escape. L3 exists to raise that boundary for
"workloads handling external/suspicious input".

`docs/specs/sandbox/backends/README.md` already compares the three L3 candidates. The
decision here is which one OpsPilot actually implements, and it is shaped by two
hard constraints already in the codebase:

1. **The entire sandbox executor is built on `docker run`** (`_build_docker_args`).
   gVisor plugs in as an alternate OCI runtime — `docker run --runtime=runsc …` —
   reusing 100% of the L2 argv and hardening. Firecracker/Kata are a *different
   execution path* (containerd/CRI shim, microVM images, KVM), i.e. a rewrite of
   the executor, not an added flag.
2. **macOS is the primary dev OS** (docs/zh/design/STAGES.md §4; cross-stage invariant #6:
   "macOS dev / Linux prod, CI must verify"). Firecracker/Kata require
   `/dev/kvm`, which is unavailable on macOS and on most nested-virt cloud
   runners. gVisor runs inside Docker Desktop's Linux VM, so the L3 argv and the
   fail-closed path stay verifiable on the dev machine and in CI.

## Decision

Implement **L3 = L2 hardened surface + gVisor `runsc`** via `--runtime=runsc`.

- `sandbox/docker_l3.py` reuses `_build_docker_args` and `_exec_docker` from the
  L2 module; the only delta is the injected `--runtime=runsc` and a daemon
  capability probe.
- `SandboxEngine(level="l2"|"l3")` selects the backend operationally. Level is an
  operator/deployment choice, **not** a field on `ActionRequest` — the proposing
  model declares the *capabilities* it needs (`requested_policy`), never the
  isolation backend. CLI surfaces it as `opspilot sandbox run --level l3`.
- **Fail-closed**: if `runsc` is not registered with the Docker daemon, L3
  refuses to run and returns an explicit error. It does **not** silently fall
  back to L2 — delivering a weaker boundary than the operator asked for is a
  security regression, not graceful degradation (consistent with the fail-closed
  posture in ADR-0005).

Firecracker/Kata are **deferred**, not rejected forever: if a future workload
needs microVM-class hardware isolation or high-density multi-tenancy (the
"strong-compliance / high-density multi-tenant" row in the backends matrix), that is a new execution path
and warrants its own ADR.

## Rationale

- Minimal, surgical delta (CLAUDE.md §2/§3): L3 is one inserted flag plus a
  probe, reusing the audited L2 path rather than forking a second executor.
- Matches OpsPilot's positioning (single-user / small-team, local-first;
  ADR-0002): gVisor covers "don't fully trust the host kernel for suspicious
  input" without standing up KVM/containerd infrastructure.
- The backends decision tree already routes the typical OpsPilot case
  ("handling external/suspicious input") to gVisor.
- Keeps the macOS-dev / Linux-prod invariant intact — L3 is exercisable in dev
  and CI; Firecracker would only ever run in prod, untested locally.

## Consequences

- L3 requires the host operator to install `runsc` and register it in
  `/etc/docker/daemon.json`. Until then, `--level l3` fails closed with a
  pointer to `docs/specs/sandbox/backends/README.md §3`.
- gVisor intercepts syscalls in user space: expect a CPU/IO cost (~10–30%,
  workload-dependent) and a small set of unsupported syscalls (e.g. some
  `io_uring` paths). The recommended rollout is to run the existing fixtures
  under `--runtime=runsc` in staging before flipping any default.
- The default backend stays **L2**. Nothing about the L2 apply path changed; L3
  is purely additive (`docker_l3.py` + an engine `level` switch).
- The Stage 5 exit criterion "sandbox L2 has run in production for one month with no escape incidents" is
  unchanged and remains a runtime observation, not a code deliverable.
