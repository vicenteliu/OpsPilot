# ADR-0005: Sandbox approval gate is a defense-in-depth signal, not a security boundary

**Status**: Accepted  
**Date**: 2026-06-05  
**Stage**: 5 hardening review

## Context

`sandbox/gate.py::check_approval_required` decides whether an action must pass
human sign-off before `apply`. It works by matching the command string against a
denylist of dangerous patterns (`rm -rf`, `DROP TABLE`, `TRUNCATE`, `chmod 777`,
fork bombs) plus environment/irreversibility flags.

A security audit found the denylist is trivially bypassable:

- Command variants evade the regexes — `rm -r -f` (split flags), `find / -delete`,
  `dd of=/dev/sda`, `mkfs`, `DELETE FROM ... ` (no `DROP`).
- Whole categories are uncovered — network side effects (`curl`/`wget` against a
  prod API), `git push --force`, `kubectl delete`.

The README described the gate as code that "blocks destructive patterns," which
oversells a heuristic denylist as if it were a security boundary.

## Decision

The approval gate is positioned as a **defense-in-depth signal and audit aid**,
**not** a security boundary. We do **not** convert it to a strict allowlist.

The real boundaries are:

1. **Docker L2 hardening** (`sandbox/docker_l2.py`) — read-only rootfs,
   `--cap-drop=ALL`, `--no-new-privileges`, seccomp, tmpfs workdir, **no host
   mounts** — contains all filesystem blast radius.
2. **Network policy** — `network.mode` controls whether the container can reach
   anything outside itself, which is what bounds non-filesystem side effects.

## Rationale

- A denylist over free-form shell strings is an unwinnable whack-a-mole; turning
  it into a reliable boundary would require an allowlist that breaks the tool's
  general-purpose action use case.
- Filesystem damage is already fully contained by the ephemeral hardened
  container, so the gate's value there is UX (don't make the operator wait) and
  audit (record that a risky pattern was seen), not protection.
- The genuine risk is **network-permitted** actions reaching real systems; that
  is addressed by tightening network policy, not by extending the denylist.

## Consequences

- README wording changed: the gate "flags" risky patterns rather than "blocks"
  them; the Docker hardening + network policy are named as the real boundary.
- Network defaults to `deny-all`; enabling network on an action forces the
  approval gate (`check_approval_required` returns `True` when network is opened).
- The denylist still gets obvious-bypass patches (split-flag `rm`, `find -delete`,
  `dd`, `mkfs`) as cheap signal improvements — but these are not relied upon as a
  boundary.
