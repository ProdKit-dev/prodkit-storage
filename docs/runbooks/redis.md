# Redis incident runbook

Use this runbook for Redis unavailability, latency, connection exhaustion, evictions,
replication/persistence problems, or a sudden rise in storage Redis command errors.

## First five minutes

1. Determine which Redis responsibilities are affected: cache, locks, idempotency,
   rate limiting, or Streams.
2. Check provider health, primary/replica state, memory, evictions, connected clients,
   blocked clients, replication lag, persistence status, and command latency.
3. Correlate the incident with deployments, key-space growth, traffic spikes,
   failovers, persistence operations, or network changes.
4. Identify whether the application can safely degrade without Redis for the
   affected responsibility.

## Containment by responsibility

- **Cache:** bypass or shorten cache use only if PostgreSQL can absorb the extra load.
  Avoid a synchronized cache stampede during recovery.
- **Distributed locks:** stop workflows that require exclusivity if lock acquisition
  cannot be trusted. Never treat Redis failure as successful lock acquisition.
- **Idempotency:** fail closed for operations where duplicate execution can cause
  financial, provisioning, or externally visible side effects.
- **Rate limiting:** choose fail-open/fail-closed behavior explicitly per endpoint;
  do not change it ad hoc during an incident without recording the risk.
- **Streams:** pause consumers/producers when ordering or durability guarantees are
  uncertain and verify consumer-group state before resuming.

## Useful commands

```text
INFO server
INFO clients
INFO memory
INFO replication
INFO persistence
INFO stats
SLOWLOG GET 20
LATENCY LATEST
CLIENT LIST
```

Avoid `KEYS *`, large synchronous deletes, or debugging commands that can block a
busy production server. Prefer `SCAN` and bounded operations.

## Recovery validation

Before declaring recovery:

- `prodkit-storage doctor` reports Redis healthy;
- command error rate and latency return to baseline;
- memory/eviction behavior is stable;
- lock acquisition/release ownership semantics are functioning;
- idempotency replay/conflict behavior is correct;
- rate-limit decisions are sensible;
- Streams publishing/consumer groups are healthy;
- PostgreSQL load caused by cache bypass has returned to normal.

Record whether data was lost, duplicated, delayed, or served stale, and add a
follow-up test if the failure mode was not already covered.
