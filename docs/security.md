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

## PostgreSQL roles

`render_role_bootstrap_sql` provides a reviewed starting point for separate
owner, migrator, runtime, read-only, and support roles. Rendered SQL must be
reviewed by the deployment team and applied through a privileged infrastructure
workflow—not automatically by the application.

The runtime role must not own RLS-protected tables and must not have
`BYPASSRLS`. `verify_rls_sync` and `verify_rls_async` check deployed role and
table properties and can fail readiness or deployment verification.

## Pydantic database-safe inputs

The optional Pydantic integration provides:

- recursive NUL-character rejection;
- trimmed strings and empty-string-to-null conversion;
- PostgreSQL int16, int32, and int64 bounds;
- `from_attributes=True` output schemas.

These validations improve error quality but do not replace database constraints.

## Supply-chain controls

CI audits Python dependencies, scans the built container for high/critical
vulnerabilities, and creates an SPDX JSON SBOM. The final application must scan
its resolved dependencies and deployed image as well.
