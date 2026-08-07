# Transactional outbox incident runbook

Use this runbook when pending-event age/backlog grows, dead events appear, workers stop
claiming, or downstream delivery repeatedly fails.

## Triage

1. Measure pending, processing, published, and dead counts plus oldest pending age.
2. Determine whether producers are healthy and whether consumers can reach the
   downstream broker/API.
3. Check worker count, claim batch size, processing latency, retry rate, and database
   lock contention.
4. Inspect representative `last_error` values without copying sensitive payloads
   into incident channels.
5. Confirm workers have unique/stable worker identities and are using lease-token
   checked completion/failure APIs.

## Containment

- If downstream is unavailable, reduce or pause dispatch pressure rather than
  generating a retry storm.
- If one poison event repeatedly fails, allow it to reach the dead state or move it
  through a reviewed maintenance workflow; do not delete history casually.
- If workers are stuck in `processing`, rely on stale-lease reclamation. Do not
  manually mark events published unless downstream delivery is independently proven.
- Scale workers only after checking database connection/lock budgets and downstream
  capacity.

## Recovery

1. Restore downstream connectivity/capacity.
2. Resume workers gradually and verify the oldest pending age is falling.
3. Confirm stale workers cannot complete events after another worker reclaims them.
4. Review dead events individually and replay only with an idempotent downstream
   contract or explicit duplicate-handling procedure.
5. Keep at-least-once semantics visible: a successful database outbox transition does
   not prove the downstream side effect happened exactly once.

## Exit criteria

- pending age and backlog return to the normal operating envelope;
- dead-event count is understood and owned;
- no sustained claim/lock errors remain;
- downstream duplicate/idempotency metrics are normal;
- database pool and transaction metrics are healthy.
