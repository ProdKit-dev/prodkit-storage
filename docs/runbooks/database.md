# Database incident runbook

Use this runbook for elevated database errors, transaction rollbacks, pool saturation,
lock contention, failed migrations, or PostgreSQL unavailability.

## First five minutes

1. Confirm whether the failure is global or isolated to one service/instance.
2. Check database health/readiness and the managed-provider status page.
3. Check connection-pool checked-out/overflow samples, query-error rate, transaction
   rollback rate, statement timeouts, deadlocks, and lock waits.
4. Correlate the first error timestamp with deployments, migrations, failovers,
   credential rotation, scaling events, or network changes.
5. Stop non-essential batch/backfill work before increasing connection limits.

## Containment

- **Pool exhaustion:** reduce application concurrency and background work first. Do
  not raise every replica's pool size independently; respect the global database
  connection budget.
- **Lock contention:** identify blockers from `pg_stat_activity`/`pg_locks`. Cancel
  the offending statement before terminating a session unless the incident requires
  stronger action.
- **Bad migration:** stop the release. Prefer a forward correction when old and new
  application versions are already mixed. Use downgrade only when the revision is
  explicitly tested as reversible.
- **Primary failure:** follow the provider failover procedure and verify DNS/endpoint
  changes before restarting large numbers of workers simultaneously.
- **Credential/role issue:** verify the runtime role is not an owner, superuser, or
  `BYPASSRLS`; validate secret rotation and connection-string propagation.

## Useful PostgreSQL queries

```sql
SELECT pid, usename, state, wait_event_type, wait_event,
       now() - query_start AS age, left(query, 500) AS query
FROM pg_stat_activity
WHERE datname = current_database()
ORDER BY query_start;
```

```sql
SELECT blocked.pid AS blocked_pid,
       blocker.pid AS blocker_pid,
       blocked.query AS blocked_query,
       blocker.query AS blocker_query
FROM pg_stat_activity AS blocked
JOIN pg_locks AS blocked_lock ON blocked_lock.pid = blocked.pid AND NOT blocked_lock.granted
JOIN pg_locks AS blocker_lock
  ON blocker_lock.locktype = blocked_lock.locktype
 AND blocker_lock.database IS NOT DISTINCT FROM blocked_lock.database
 AND blocker_lock.relation IS NOT DISTINCT FROM blocked_lock.relation
 AND blocker_lock.page IS NOT DISTINCT FROM blocked_lock.page
 AND blocker_lock.tuple IS NOT DISTINCT FROM blocked_lock.tuple
 AND blocker_lock.virtualxid IS NOT DISTINCT FROM blocked_lock.virtualxid
 AND blocker_lock.transactionid IS NOT DISTINCT FROM blocked_lock.transactionid
 AND blocker_lock.classid IS NOT DISTINCT FROM blocked_lock.classid
 AND blocker_lock.objid IS NOT DISTINCT FROM blocked_lock.objid
 AND blocker_lock.objsubid IS NOT DISTINCT FROM blocked_lock.objsubid
 AND blocker_lock.pid <> blocked_lock.pid
 AND blocker_lock.granted
JOIN pg_stat_activity AS blocker ON blocker.pid = blocker_lock.pid;
```

## Recovery validation

Before declaring recovery:

- `prodkit-storage doctor` reports healthy PostgreSQL/PostGIS;
- `prodkit-storage schema-check` reports a compatible schema revision;
- query-error and rollback rates return to baseline;
- pool utilization and lock waits stabilize;
- tenant isolation/read-only enforcement still work if roles or policies changed;
- outbox backlog begins draining without a dead-event spike.

Document the trigger, customer impact, containment, recovery, and follow-up actions.
