# Sandbox — Detailed Spec

## 1. Action type contract

| `type` | Purpose | Default network | Default filesystem | Notes |
|---|---|---|---|---|
| `shell` | Arbitrary shell command | deny-all | overlay tmpfs | Most common; always dry-run |
| `script` | Run a script (python/bash/ansible) | deny-all | overlay tmpfs | Requires `interpreter` and an entrypoint |
| `http` | HTTP request | allowlisted hosts only | no file writes | method/headers/body must be explicit |
| `sql_readonly` | Read-only SQL query | allowlisted data sources only | no file writes | Enforces `READ ONLY` transactions; DDL/DML forbidden |
| `workflow_dryrun` | n8n / Argo / Airflow trial run | per workflow policy | nothing persisted | Returns only the execution plan and sample output |

Every action must include `requested_policy` (even as an empty object), explicitly declaring the capabilities it needs.

## 2. Action envelope

The authoritative field definitions live in `templates/action-request.template.yaml`. Core fields:

| Field | Required | Description |
|---|---|---|
| `id` | ✓ | `act_<ULID>` |
| `session_id` | ✓ | Associated Session |
| `proposed_by` | ✓ | `model:<name>:<version>` or `user:<id>` |
| `type` | ✓ | See table above |
| `payload` | ✓ | Type-specific parameters (command/script/http/sql/workflow) |
| `requested_policy` | ✓ | Requested grants for network/fs/resource/secrets |
| `dry_run` | ✓ | bool, defaults to `true` |
| `approval_required` | ✓ | bool; computed by `approval-policy` |
| `expected_effects` | ✗ | Side effects the model claims it will produce (for auditing) |
| `rollback_hint` | ✗ | The model's own description of how to roll back (see §6) |

## 3. Action lifecycle

```
proposed ──▶ validated ──▶ dry_run ──▶ [approval?] ──▶ applied ──▶ recorded
   │             │             │             │            │
   └──▶ rejected └──▶ rejected └──▶ aborted  └──▶ rejected └──▶ failed
```

State semantics:
- **proposed**: envelope generated, not yet schema-validated
- **validated**: passed schema + static policy validation
- **dry_run**: executed in the sandbox, but external side effects are forbidden (apply-style actions become plans)
- **approval**: entered when an approval gate threshold is exceeded; records approver/time/decision
- **applied**: actually executed (still inside the sandbox, but side effects permitted by the granted config are allowed)
- **recorded**: all stdout/stderr/diff/exit codes have been written back to the Session
- **rejected/aborted/failed**: error terminal states; the failure reason must be written to `tool_result`

## 4. Policy contract

### 4.1 Network

```yaml
network:
  mode: deny-all | allowlist | open      # default deny-all
  egress:
    - host: pkg.debian.org              # exact domain match
    - cidr: 10.0.0.0/8                  # internal network range
  dns:
    resolvers: [1.1.1.1, 8.8.8.8]
    block_dot_local: true
```

Template: `policies/network-allowlist.template.yaml`

### 4.2 Filesystem

```yaml
fs:
  rootfs: read_only
  workdir: /work                         # tmpfs overlay
  mounts:
    - source: <session>/inputs           # redacted inputs from the Session
      target: /input
      mode: ro
    - source: <session>/artifacts        # artifact output
      target: /output
      mode: rw
  forbidden:
    - /home/**/.ssh
    - /home/**/.aws
    - /home/**/.kube
    - /var/run/docker.sock
```

### 4.3 Resource

Template: `policies/resource-quota.template.yaml`; common keys:
- `cpu`: CPU quota (cores or percentage)
- `memory`: memory limit
- `pids`: maximum number of processes
- `disk`: tmpfs limit
- `timeout`: wall-clock timeout (default 30 s)

### 4.4 Syscalls

- Uses the Docker default seccomp profile by default
- Hardened mode uses `policies/seccomp.template.json` (a stricter allowlist)
- High-risk syscalls disabled by default: `mount`, `umount`, `reboot`, `kexec_load`, `init_module`, `delete_module`, `bpf`, `ptrace` (unless explicitly allowed)

### 4.5 Secrets

- Injecting sensitive credentials via env/argv is **not allowed**
- Must go through the Secrets Broker interface; short-lived credentials are mounted at `/run/secrets/<name>` for the duration of the action and unmounted automatically when it ends
- The broker implementation choice is deferred; this spec only defines the interface shape:

```
GET  /broker/v1/lease  body: {action_id, name, ttl_seconds}
                       resp: {value, expires_at}
POST /broker/v1/release body: {lease_id}
```

## 5. Dry-run semantics

- `shell` / `script`: executed inside the container, but writes to mount points are redirected to an overlay on top of the overlay; a diff view is produced
- `http`: only returns "a summary of the request that would be sent + an equivalent curl command"; nothing is actually sent
- `sql_readonly`: may execute (it is read-only by nature); returns the row count and samples
- `workflow_dryrun`: calls the workflow engine's plan/dry-run interface

Dry-run artifacts must include:
- The command/request/SQL that would be executed (redacted)
- The list of expected file changes
- The expected network access targets
- A best-effort estimate of expected resource usage

## 6. Rollback hints

In `rollback_hint`, the model should provide best-effort "inverse operation" suggestions:
- File changes → backup directory path + restore command
- Package installs → `apt-get remove <pkg>` or snapshot rollback
- Config changes → backup file sha256 and restore command
- Irreversible actions (deletions) → explicitly mark `irreversible: true`, which always triggers the approval gate

## 7. Approval gate

Trigger conditions (any one triggers it):
1. `payload` contains dangerous keywords: `rm -rf`, `DROP`, `TRUNCATE`, `chmod 777`, `:(){ :|:& };:`
2. The target environment label is `prod` / `production`
3. Involves IAM / RBAC / network policy changes
4. Network egress exceeds the current allowlist
5. `irreversible: true`

Template: `templates/approval-policy.template.yaml`

## 8. Recording

After each action completes, the following must be written to the Session:
- One `tool_result` trace event (with exit_code, usage summary, artifact_ids)
- One or more artifacts:
  - `stdout`/`stderr`: anything over 8 KiB goes to an artifact, otherwise inline
  - `diff`: diff between the dry-run and apply outputs
  - `manifest`: snapshot of the policy actually applied (for post-hoc auditing)

## 9. Failure modes

| Failure class | Handling |
|---|---|
| Schema validation failure | Return `rejected`; do not enter dry_run |
| Policy validation failure (request exceeds what is allowed) | Return `rejected`; suggest a downgraded alternative |
| Timeout | Force-kill the container; set state to `failed`; record the `timeout` flag |
| OOM | State `failed`; record `oom_killed` |
| Network violation (attempt to reach a non-allowlisted target) | Abort the action; record the violation event; state `aborted` |
| Backend failure (docker daemon down) | State `failed`; report to audit.log |

## 10. Hard requirements

- Every action must have dry_run stage artifacts (even if it is ultimately applied)
- The sandbox process must never escape into the host namespaces (PID/NET/USER/MNT must be isolated)
- `requested_policy` must be listed explicitly; anything omitted is treated as deny
- All logs use UTF-8 + RFC3339 timestamps
- Backend implementations are replaceable, but must satisfy the interfaces and fields above
