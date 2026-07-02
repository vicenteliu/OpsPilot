# Sandbox — Execution Spec

> **Status**: spec-only — action contracts, policies, and backend selection docs. No runtime here.

## TL;DR
Sandbox = the isolated execution layer for AI-proposed actions (commands / scripts / workflows / HTTP / read-only SQL): "run it for you first, then decide whether to apply." **Dry-run by default**, **deny-all network by default**, **no secrets by default**.

## Principles

1. **Default deny**: network, filesystem, secrets, syscalls — everything is denied by default and allowed on demand.
2. **Dry-run first**: every action enters dry-run by default, producing a diff / the commands that would run; only an explicit `--apply` takes effect.
3. **Recordable**: stdin, argv, env, stdout, stderr, file changes, exit code — all written back to the Session.
4. **Reversible by design**: apply requires prior dry-run artifacts; high-risk actions require an approval gate + rollback guidance.
5. **Pluggable isolation**: from Docker (default) → gVisor/Firecracker (strong isolation) → remote VM (production canary).

## Backend selection matrix

| Backend | Isolation strength | Startup overhead | Complexity | Recommended scenarios |
|---|---|---|---|---|
| Docker (L1) | Medium | Low (sub-second) | Low | **Default**: dev machines, self-hosted, internal-network pilots |
| Docker hardened (L2) | Medium-high | Low | Medium | seccomp/AppArmor + cap-drop + RO rootfs |
| gVisor | High | Medium | Medium | Handling suspicious/external input; multi-tenant shared hosts |
| Firecracker / Kata | Very high | Medium (microVM, ~100 ms range) | Medium-high | Strong isolation requirements; needs a KVM host |
| Remote VM | Environment-dependent | High | High | Production canary; cross-region execution |

See `backends/README.md` for details.

## Scope

In scope:
- Action type contracts (shell / script / http / sql_readonly / workflow_dryrun)
- Policy contract (network / fs / resource / secrets)
- Dry-run vs apply semantics
- Recording fields and write-back conventions
- Approval gate trigger conditions

Out of scope:
- Concrete backend implementations (dockerfiles, image build scripts)
- Network proxy implementation
- Secrets management implementation (interface conventions only)

## Directory layout

```
sandbox/
├── README.md                                # This file
├── SPEC.md                                  # Action contract + policy contract + lifecycle
├── backends/
│   └── README.md                            # Comparison and selection guide for the 5 backend types
├── policies/
│   ├── network-allowlist.template.yaml      # Network egress allowlist
│   ├── seccomp.template.json                # seccomp baseline
│   └── resource-quota.template.yaml         # CPU/memory/disk/timeout
└── templates/
    ├── action-request.template.yaml         # Action request envelope
    └── approval-policy.template.yaml        # Approval gate rules
```

## Action lifecycle (high level)

```
proposed → validated → dry_run → [approval?] → applied → recorded
                                       │
                                       └──▶ rejected / aborted
```

See `SPEC.md` for detailed state semantics.

## Contracts with other directories

| Upstream | Input to Sandbox |
|---|---|
| `session/` | trace event `tool_call` → converted into an action request |
| `playbooks/` | action templates and policy recommendations |

| Downstream | Artifacts provided by Sandbox |
|---|---|
| `session/` | recording → trace event `tool_result` + artifact |
| `harness/` | sandbox execution results as evaluator input |

## Hard nos

- ❌ Never mount the user host's credential directories such as `~/.ssh`, `~/.aws`, `~/.kube`
- ❌ Never inject secrets/tokens via environment variables or arguments; they must go through the Secrets Broker interface
- ❌ Never let the sandbox call production APIs directly, unless explicitly applied (`apply`) and approved
- ❌ Never auto-execute high-risk actions such as `rm -rf` / `DROP` / `DELETE` / IAM changes

## Open questions

- [ ] Secrets Broker interface choice: local file-based vs Vault agent vs SPIFFE/SPIRE?
- [ ] Recording artifact encryption: default plaintext + filesystem-level encryption (LUKS/eCryptfs)?
- [ ] Is the gVisor experience on macOS hosts (requires a Linux VM intermediary) worth including in the default recommendation?
