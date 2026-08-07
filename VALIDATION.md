# Validation report

Validated on 2026-08-06 against the source tree in this release.

## Completed checks

- 56 unit tests passed.
- Statement and branch-aware coverage measured 89.92%; the configured minimum is 80%.
- Every Python source file compiled successfully.
- All 35 importable package modules loaded successfully in the validation runtime.
- SQLAlchemy configured both bundled ORM mappers and their tables successfully.
- Alembic generated the complete offline PostgreSQL/PostGIS upgrade SQL from base to head.
- `pyproject.toml`, Compose, workflow, and pre-commit YAML parsed successfully.
- Source and test line-length checks passed under the repository's 100-character policy, with the documented Alembic migration exception.

## Environment limitations

The execution environment's Python package registry did not expose all declared dependencies, and Docker was unavailable. Therefore this environment could not run:

- a fresh `uv sync --all-extras` using the public dependency set;
- Ruff and mypy with their released packages;
- live PostgreSQL/PostGIS and Redis integration tests;
- the container build and Compose health checks.

For code-level validation, the environment's installed SQLAlchemy, Alembic, Pydantic, and Pydantic Settings packages were used. Small temporary import-surface stubs were used only for unavailable Redis and GeoAlchemy2 packages; those stubs are not included in this repository or archive.

The GitHub Actions workflow performs dependency installation, Ruff, strict mypy, offline migration generation, unit coverage, and service-backed integration tests against PostgreSQL/PostGIS and Redis. Run that workflow and the deployment checklist before treating a release as approved for a production environment.

This repository is a production-oriented storage foundation, not proof that any particular deployment is production-ready. Backups, restore drills, HA/failover, network controls, secrets, capacity, compliance, and incident operations remain deployment responsibilities.
