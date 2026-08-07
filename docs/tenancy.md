# Multi-tenancy and PostgreSQL RLS

## Recommended default

Use a shared schema with a non-null `tenant_id` on tenant-owned rows, composite uniqueness that includes `tenant_id`, application tenant context, and PostgreSQL Row-Level Security for defense in depth.

Schema-per-tenant or database-per-tenant may be justified for regulatory isolation, customer-managed encryption, regional placement, noisy-neighbor control, or very large tenants, but lifecycle and migration costs are much higher.

## Critical role separation

PostgreSQL table owners normally bypass RLS. The production runtime role should not own protected tables and should not have `BYPASSRLS` or superuser privileges.

A common role model is:

```text
storage_owner       owns schema, tables, functions, migrations
storage_migrator    can assume storage_owner only in deployment jobs
storage_app         runtime DML; subject to RLS
storage_readonly    restricted support/reporting role
```

Use `FORCE ROW LEVEL SECURITY` when the table owner should also be subject to policies during tests or controlled operations.

## Enabling a policy in a migration

```python
from prodkit_storage.alembic.rls import disable_tenant_rls, enable_tenant_rls


def upgrade() -> None:
    enable_tenant_rls(op, "customers", schema="app")


def downgrade() -> None:
    disable_tenant_rls(op, "customers", schema="app")
```

The generated policy compares `tenant_id` with the transaction-local setting `app.tenant_id`.

## Runtime configuration

```dotenv
PRODKIT_STORAGE_TENANT_RLS_ENABLED=true
PRODKIT_STORAGE_TENANT_REQUIRED=true
```

Every tenant transaction must execute inside a `RequestContext`. The session event applies transaction-local values after `BEGIN`:

```sql
SELECT set_config('app.tenant_id', '<uuid>', true);
SELECT set_config('app.actor_id', '<uuid>', true);
SELECT set_config('app.request_id', '<request-id>', true);
```

The final argument `true` makes the setting transaction-local, preventing connection-pool leakage after commit or rollback.

## Testing requirements

Test RLS with the actual runtime role, never only with the table owner or PostgreSQL superuser. Include tests for:

- tenant A cannot read tenant B rows;
- tenant A cannot insert or update a row assigned to tenant B;
- missing tenant context fails closed;
- support/admin access uses a separately reviewed policy or separately authenticated role;
- background jobs explicitly set tenant context;
- pooled connections do not retain a previous tenant setting;
- raw SQL and bulk operations remain isolated.

## Indexing

Tenant-first indexes are usually required for tenant-scoped access patterns:

```sql
CREATE INDEX ix_customers_tenant_created
ON customers (tenant_id, created_at DESC, id DESC);
```

Global identifiers should still include tenant scope unless they are intentionally globally unique:

```sql
CREATE UNIQUE INDEX uq_customers_tenant_external_id
ON customers (tenant_id, external_id)
WHERE deleted_at IS NULL;
```

## Support and platform administration

Do not implement support access by omitting tenant context or using a superuser in the application. Prefer audited, time-bounded impersonation or a dedicated policy based on independently verified claims. Every cross-tenant action should include actor, reason, request, and target tenant in the audit trail.
