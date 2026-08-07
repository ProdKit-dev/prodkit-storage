# Migration policy

## Ownership

Run migrations in a dedicated release job with a migrator login role. Web and
worker processes should not automatically migrate on startup. This prevents race
conditions, privilege expansion, and unpredictable startup latency.

The recommended role model separates login identity from object ownership:

```text
migrator (LOGIN, NOINHERIT)
    -> SET ROLE owner
owner (NOLOGIN)
    -> owns schema, tables, constraints, indexes, functions
runtime
    -> never owns application tables
```

Use `render_role_bootstrap_sql` in a privileged infrastructure workflow, then
configure Alembic with:

```dotenv
PRODKIT_STORAGE_MIGRATION_OWNER_ROLE=prodkit_owner
```

The bundled Alembic environment issues `SET ROLE` before schema changes when
that setting is configured. This keeps new objects owned by the owner role and
makes `ALTER DEFAULT PRIVILEGES FOR ROLE <owner>` effective.

After a migration, apply the reviewed output of
`render_post_migration_grants_sql` so existing objects receive the expected
runtime/read-only/support privileges and shared audit/outbox restrictions.

## Privileged database bootstrap

PostGIS and other privileged extensions are not routine application migrations.
Provision them through Terraform, a managed database configuration workflow, a
DBA/bootstrap job, or the development Compose init scripts. A routine migrator
must not need superuser privileges merely to apply application schema changes.

## Expand and contract

For rolling or zero-downtime deployments:

1. **Expand:** add nullable columns, new tables, indexes, or compatible code paths.
2. **Backfill:** update data in bounded batches with observability and resumability.
3. **Switch:** deploy code that reads/writes the new representation.
4. **Enforce:** add `NOT NULL`, checks, or uniqueness after validation.
5. **Contract:** remove old columns or behavior only after every old process is gone.

Do not combine a large table rewrite with the application deployment that first requires it.

## Index creation

Use `CREATE INDEX CONCURRENTLY` for large live tables. PostgreSQL does not allow
it inside a normal transaction, so use an Alembic migration with
`autocommit_block()`:

```python
with op.get_context().autocommit_block():
    op.create_index(
        "ix_orders_tenant_created",
        "orders",
        ["tenant_id", "created_at"],
        postgresql_concurrently=True,
    )
```

Also set a suitable `lock_timeout` so a migration fails instead of blocking
production traffic indefinitely.

## Constraint validation

For large tables, add checks or foreign keys as `NOT VALID`, backfill/fix data,
then validate separately:

```sql
ALTER TABLE child
ADD CONSTRAINT fk_child_parent
FOREIGN KEY (parent_id) REFERENCES parent(id) NOT VALID;

ALTER TABLE child VALIDATE CONSTRAINT fk_child_parent;
```

## PostGIS

Enable the extension once per database in the privileged bootstrap layer. Do
not drop it in ordinary application downgrade migrations because unrelated
schemas can depend on its types and functions. Upgrade extension binaries under
a tested maintenance procedure and run the recommended extension upgrade
command.

## Application model discovery

The bundled Alembic environment always loads the storage audit/outbox models.
For application models, set a comma-separated list of importable modules whose
models inherit `prodkit_storage.Base`:

```dotenv
PRODKIT_STORAGE_ALEMBIC_MODEL_MODULES=myapp.models,myapp.orders.models
```

Importing a package that does not itself import its model modules is
insufficient; list the concrete modules that register mapped classes with
`Base.metadata`.

## Autogenerate review

Alembic autogenerate is a draft, not an approval system. Review:

- destructive operations and accidental renames;
- server defaults and data backfills;
- lock duration and table rewrites;
- enum/type lifecycle;
- PostGIS-generated indexes;
- partial and expression indexes;
- RLS policies, grants, views, functions, and triggers;
- downgrade safety.

Published migrations should normally remain immutable. The `v0.2.1` correction
removes privileged extension creation from the original pre-1.0 bootstrap
revision so fresh installs work with the documented least-privilege migrator;
existing databases already stamped at that revision are unaffected.

## CI checks

The repository workflow verifies:

- fresh installation to Alembic head;
- offline migration SQL generation;
- metadata drift with `alembic check`;
- live PostgreSQL/PostGIS and Redis integration behavior;
- downgrade of one supported revision and roll-forward to head;
- lint, strict typing, dependency audit, image scanning, and SBOM generation.

Before `1.0.0`, expand this into an oldest-supported-release upgrade matrix when
more than one production revision must be supported concurrently.

## Custom schema

When `PRODKIT_STORAGE_DATABASE_SCHEMA` is not `public`, create and grant the
schema before running Alembic. The bundled environment sets that schema as the
migration default and creates package tables there; it does not provision
database-level ownership or grants.
