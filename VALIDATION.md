# Validation report

Validated on 2026-08-07 against the source tree in this combined `0.2.0` release.

## Completed checks

- 79 unit tests passed.
- Statement- and branch-aware coverage measured 84.67%; the configured minimum is 80%.
- Every Python source and test file compiled successfully.
- All 53 importable package modules loaded successfully in the validation runtime.
- SQLAlchemy configured both bundled ORM mappers and their tables successfully.
- Alembic generated the complete 80-line offline PostgreSQL/PostGIS upgrade SQL from base to head.
- `pyproject.toml`, Compose, workflow, Dependabot, and pre-commit YAML parsed successfully.
- Source and test line-length checks passed under the repository's 100-character policy, with the documented Alembic migration exception.
- Explicit sync and async offset-count statements are covered to prevent SQLAlchemy clause truthiness regressions.

The unit suite covers the original storage behavior plus the combined release additions: typed
read/write sessions, allowlisted filtering and sorting, sort-bound keyset cursors, optional offset
pagination, repository streaming and row-lock modes, SQLSTATE handling, enum types, audit
classification and redaction, secret providers, role/RLS verification, observability hooks,
FastAPI/Pydantic integrations, Redis instrumentation, and outbox metrics.

## Environment limitations

The execution environment's Python package registry did not expose all declared dependencies, and
Docker was unavailable. Therefore this environment could not run:

- a fresh `uv sync --all-extras` using the public dependency set;
- Ruff and strict mypy with the released dependency graph;
- live PostgreSQL/PostGIS and Redis integration tests;
- the image build, Trivy scan, SBOM generation, and Compose health checks.

For code-level validation, the environment's installed SQLAlchemy, Alembic, Pydantic, and Pydantic
Settings packages were used. Small temporary import-surface stubs were used only for unavailable
Redis and GeoAlchemy2 packages; those stubs are not included in this repository or patch.

The GitHub Actions workflow performs dependency installation, Ruff, strict mypy, offline and live
migrations, unit coverage, service-backed PostgreSQL/PostGIS and Redis integration tests, dependency
auditing, container vulnerability scanning, and SPDX SBOM generation. Run that workflow and the
deployment checklist before approving a release for production.

This repository is a production-oriented persistence foundation, not proof that any particular
deployment is production-ready. Backups, restore drills, HA/failover, network controls, secrets,
capacity, compliance, and incident operations remain deployment responsibilities.
