# Migration policy

## Ownership

Run migrations in a dedicated release job with a migrator role. Web and worker processes should not automatically migrate on startup. This prevents race conditions, privilege expansion, and unpredictable startup latency.

## Expand and contract

For rolling or zero-downtime deployments:

1. **Expand:** add nullable columns, new tables, indexes, or compatible code paths.
2. **Backfill:** update data in bounded batches with observability and resumability.
3. **Switch:** deploy code that reads/writes the new representation.
4. **Enforce:** add `NOT NULL`, checks, or uniqueness after validation.
5. **Contract:** remove old columns or behavior only after every old process is gone.

Do not combine a large table rewrite with the application deployment that first requires it.

## Index creation

Use `CREATE INDEX CONCURRENTLY` for large live tables. PostgreSQL does not allow it inside a normal transaction, so use an Alembic migration with `autocommit_block()`:

```python
with op.get_context().autocommit_block():
    op.create_index(
        "ix_orders_tenant_created",
        "orders",
        ["tenant_id", "created_at"],
        postgresql_concurrently=True,
    )
```

Also set a suitable `lock_timeout` so a migration fails instead of blocking production traffic indefinitely.

## Constraint validation

For large tables, add checks or foreign keys as `NOT VALID`, backfill/fix data, then validate separately:

```sql
ALTER TABLE child
ADD CONSTRAINT fk_child_parent
FOREIGN KEY (parent_id) REFERENCES parent(id) NOT VALID;

ALTER TABLE child VALIDATE CONSTRAINT fk_child_parent;
```

## PostGIS

Enable the extension once per database. Do not drop it in ordinary application downgrade migrations because unrelated schemas can depend on its types and functions. Upgrade extension binaries under a tested maintenance procedure and run the recommended extension upgrade command.

## Application model discovery

The bundled Alembic environment always loads the storage audit/outbox models. For application models, set a comma-separated list of importable modules whose models inherit `prodkit_storage.Base`:

```dotenv
PRODKIT_STORAGE_ALEMBIC_MODEL_MODULES=myapp.models,myapp.orders.models
```

Importing a package that does not itself import its model modules is insufficient; list the concrete modules that register mapped classes with `Base.metadata`.

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

## CI checks

At minimum:

- migrate a fresh database to head;
- run application integration tests;
- downgrade one revision where supported;
- upgrade again;
- compare metadata/autogenerate for unexpected drift;
- test from the oldest supported production revision to head.

## Custom schema

When `PRODKIT_STORAGE_DATABASE_SCHEMA` is not `public`, create and grant the schema before running Alembic. The bundled environment sets that schema as the migration default and creates package tables there; it does not provision database-level ownership or grants.
