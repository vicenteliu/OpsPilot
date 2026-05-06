---
doc_id: doc_c9d0e1f2
title: Database Connection Pool Exhaustion SOP
valid_from: 2026-02-15
source_authority: official
---

# Database Connection Pool Exhaustion SOP

> Scope: PostgreSQL and MySQL with connection poolers (PgBouncer, ProxySQL). Applies to both RDS and self-managed instances.

## 1. Symptoms and Root Causes

**Symptoms** — any of the following indicate pool exhaustion:

- Application logs: `too many connections`, `connection timeout`, `FATAL: remaining connection slots are reserved`
- Database metric: `pg_stat_activity` count ≈ `max_connections` (PostgreSQL) or `Threads_connected` ≈ `max_connections` (MySQL)
- Latency spike on all queries with no CPU/disk pressure on the DB host
- PgBouncer: `cl_waiting > 0` in `SHOW POOLS`

**Root Causes**

| Cause | Signal |
|---|---|
| Connection leak (app not closing connections) | `pg_stat_activity` shows idle connections > 1 h |
| Sudden traffic spike | Request rate increase + connection count correlated |
| Long-running transaction holding connection | `pg_stat_activity.state = 'idle in transaction'` + high `xact_start` age |
| Pool size misconfiguration | `pool_size` in pooler config < peak concurrency demand |
| Missing connection pooler (app connects directly) | `max_connections` reached with < 100 clients |

## 2. Resolution Steps

### 2.1 Immediate Mitigation

1. **Kill idle connections** (PostgreSQL):
   ```sql
   SELECT pg_terminate_backend(pid)
   FROM pg_stat_activity
   WHERE state = 'idle' AND state_change < now() - interval '10 minutes';
   ```
2. **Kill long-running idle-in-transaction**:
   ```sql
   SELECT pg_terminate_backend(pid)
   FROM pg_stat_activity
   WHERE state = 'idle in transaction' AND xact_start < now() - interval '5 minutes';
   ```
3. **Temporarily increase `max_connections`** (requires DB restart — confirm with DBA first): edit `postgresql.conf` or RDS parameter group.
4. **Reduce pool size pressure**: in PgBouncer, `SET pool_size=<lower>` per database to shed load to a waiting queue rather than the DB itself.

### 2.2 Root-Cause Fix

- **Leak**: Add connection-close in application finally/defer blocks. Add `idle_in_transaction_session_timeout = 120s` to DB config.
- **Traffic spike**: Scale the connection pooler horizontally (PgBouncer is stateless — add instances).
- **Missing pooler**: Deploy PgBouncer in transaction mode between the application and the DB; reduce application `max_pool_size` to 5–10 per instance.
- **Misconfiguration**: Set `pool_size = (max_connections - superuser_reserved) / num_app_instances`.

**Escalation criteria**: `max_connections` already at system limit AND RDS instance at max memory → escalate to DBA for instance resize or read-replica offload.
