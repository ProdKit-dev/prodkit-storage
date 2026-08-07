# Terraform deployment contract

ProdKit Storage intentionally does not ship a fake provider-agnostic database module.
PostgreSQL/PostGIS and Redis capabilities differ materially across AWS, GCP, Azure,
Hetzner/self-managed, Fly, Railway, and other platforms. This directory defines the
**contract** a production Terraform stack should satisfy; provider-specific modules can
implement it without changing application code.

## PostgreSQL requirements

The stack should expose or provision:

- one primary PostgreSQL endpoint and optional explicit read-replica endpoint;
- TLS-enforced private networking;
- a PostgreSQL version supported by the application and PostGIS version tested by CI;
- PostGIS plus other approved extensions provisioned outside routine Alembic migrations;
- automated backups/PITR with documented retention and restore procedure;
- multi-zone/high-availability configuration when required by the product RPO/RTO;
- parameter settings compatible with application statement/lock/idle timeouts;
- metrics/log export for connections, CPU, memory, storage, I/O, locks, replication,
  backup freshness, and failover events;
- owner/migrator/runtime/read-only/support roles created from reviewed bootstrap SQL;
- secrets delivered through the platform secret manager, never Terraform output in
  plaintext application logs.

Recommended Terraform outputs consumed by deployment automation:

```hcl
output "postgres_primary_secret_ref" { value = "..." }
output "postgres_read_secret_ref"    { value = "..." }
output "postgres_ca_secret_ref"      { value = "..." }
output "postgres_database_name"      { value = "..." }
```

Prefer secret **references**, not passwords or complete DSNs, as Terraform outputs.

## Redis requirements

The stack should expose or provision:

- TLS/private endpoint;
- authentication/ACLs;
- a topology matching required durability and availability;
- max-memory and eviction policy chosen deliberately for the workload;
- persistence/replication appropriate for locks, idempotency, rate limiting, and Streams;
- metrics for memory, evictions, latency, clients, blocked clients, replication, and
  persistence failures;
- backup/export capability where the chosen Redis responsibility requires it.

Recommended output:

```hcl
output "redis_secret_ref" { value = "..." }
```

## Deployment sequence

A production release pipeline should execute these responsibilities separately:

```text
Terraform / privileged bootstrap
  -> extensions, network, roles, secrets, managed-service configuration

Migration job (prodkit_migrator)
  -> SET ROLE owner
  -> prodkit-storage migration-check for new revision source
  -> alembic upgrade head
  -> reviewed post-migration grants
  -> prodkit-storage schema-check

Application rollout (prodkit_runtime)
  -> web / workers / schedulers
  -> readiness and telemetry verification
```

## Required verification

Before accepting a provider module as production-ready, run:

1. create from empty infrastructure;
2. migrate a fresh database;
3. restore a real logical/provider backup into a scratch database;
4. simulate primary failover where supported;
5. rotate database and Redis credentials;
6. verify RLS using a non-owner runtime role;
7. test application behavior when Redis is unavailable;
8. confirm dashboards and alert delivery;
9. record measured RPO/RTO instead of relying only on provider marketing values.
