## Summary

<!-- What problem does this PR solve, and why does it belong in ProdKit Storage? -->

## Changes

<!-- Describe the implementation and important design choices. -->

## Compatibility and risk

<!-- Public API, migrations, data integrity, RLS/security, concurrency, performance, Redis/PostgreSQL, or deployment impact. Write "None" where genuinely not applicable. -->

## Validation

<!-- List the commands/tests you ran and any relevant live integration evidence. -->

## Checklist

- [ ] The change is focused and follows `AGENTS.md` and `MAINTENANCE.md`.
- [ ] No secrets, credentials, private data, or production data are included.
- [ ] Public behavior and documentation are updated where needed.
- [ ] Sync and async behavior remain aligned where applicable.
- [ ] Existing published Alembic revisions were not modified, renamed, or deleted.
- [ ] New migrations pass `prodkit-storage migration-check` and use a safe rollout strategy.
- [ ] Tests cover the regression/new behavior, including live infrastructure paths where relevant.
- [ ] `uv.lock` is current and the locked dependency graph installs successfully.
- [ ] Ruff, strict mypy, pytest/coverage, migration checks, and required CI gates pass.
- [ ] Security, operational, compatibility, and rollback implications are documented.
- [ ] Review conversations are resolved or explicitly answered before merge.
