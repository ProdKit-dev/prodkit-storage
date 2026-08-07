# Security integrations

## Audit classification and redaction

Audit snapshots are sanitized before persistence. The default policy drops
common secret fields and masks regulated identifiers.

```python
from prodkit_storage.security import (
    AuditAction,
    AuditPolicy,
    DataClassification,
    NameClassifier,
)

policy = AuditPolicy(
    classifiers=(
        NameClassifier(
            paths={"billing.card_number": DataClassification.REGULATED},
            leaf_names={"email": DataClassification.PERSONAL},
        ),
    ),
    classification_actions={
        DataClassification.PERSONAL: AuditAction.HASH,
        DataClassification.REGULATED: AuditAction.REJECT,
    },
    hash_secret=b"separate-audit-hmac-secret",
)
```

Applications must extend the classifier for their own regulated, contractual,
and domain-sensitive fields. Redaction is not a substitute for minimizing audit
payloads.

## Secret providers

The package defines synchronous and asynchronous provider protocols rather than
binding to one cloud:

```python
settings = load_storage_settings(
    provider,
    (
        SecretBinding("database_url", "prod/database-url"),
        SecretBinding("redis_url", "prod/redis-url"),
        SecretBinding("cursor_signing_secret", "prod/cursor-secret"),
    ),
)
```

Adapters can be implemented for Vault, AWS Secrets Manager, Google Secret
Manager, Azure Key Vault, Kubernetes-mounted secrets, or another approved
system. Rotation and lease renewal remain provider/deployment responsibilities.

`PRODKIT_STORAGE_ENVIRONMENT=staging` and `production` reject the package's known
development cursor-signing secret. Production deployments must supply a unique,
secret value through their approved secret delivery path.

## PostgreSQL roles

`render_role_bootstrap_sql` provides a reviewed starting point for separate
owner, migrator, runtime, read-only, and support roles. Passwords and extension
installation stay in a privileged infrastructure workflow.

The recommended ownership flow is:

```text
prodkit_migrator (LOGIN, NOINHERIT)
        |
        | SET ROLE
        v
prodkit_owner (NOLOGIN, schema/object owner)
```

Set:

```dotenv
PRODKIT_STORAGE_MIGRATION_OWNER_ROLE=prodkit_owner
```

when Alembic connects as the migrator. The migrator has membership in the owner
role but does not receive direct schema `CREATE`; this prevents accidentally
creating objects owned by the login role and ensures owner-scoped default
privileges apply consistently.

After migrations, apply the reviewed output of
`render_post_migration_grants_sql`. It grants normal runtime DML for application
tables while making `storage_audit_events` append-only for the runtime role and
withholding outbox deletion from the runtime role.

The runtime role must not own RLS-protected tables and must not have
`BYPASSRLS`. `verify_rls_sync` and `verify_rls_async` check deployed role and
table properties and can fail readiness or deployment verification.

## Privileged PostgreSQL extensions

Routine Alembic revisions do not install PostGIS or other privileged extensions.
Provision approved extensions during database bootstrap (managed-service setup,
Terraform, DBA workflow, or the development Compose init script) before models
that require them are migrated. This keeps routine application migrations on a
least-privilege role.

## Pydantic database-safe inputs

The optional Pydantic integration provides:

- recursive NUL-character rejection;
- trimmed strings and empty-string-to-null conversion;
- PostgreSQL int16, int32, and int64 bounds;
- `from_attributes=True` output schemas.

These validations improve error quality but do not replace database constraints.

## Supply-chain controls

GitHub Actions audits Python dependencies, scans the built container for
high/critical vulnerabilities, creates an SPDX JSON SBOM, and runs the live
PostgreSQL/PostGIS and Redis integration suite. The final application must scan
its resolved dependencies and deployed image as well.
