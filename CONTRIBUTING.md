# Contributing to ProdKit Storage

Thanks for contributing. ProdKit Storage is a deliberately small persistence foundation, so changes should solve a demonstrated shared storage need without turning the package into an application framework.

Before contributing, read [AGENTS.md](AGENTS.md), [MAINTENANCE.md](MAINTENANCE.md), [SECURITY.md](SECURITY.md), and the [Code of Conduct](CODE_OF_CONDUCT.md).

## What belongs here

Good contributions include correctness fixes, security fixes, compatibility improvements, operational guardrails, documentation, tests, and small reusable APIs needed by multiple consuming applications.

Product-specific models, business workflows, provider-specific infrastructure presented as universal defaults, and speculative abstractions generally belong in the consuming application instead.

For a substantial feature or public-API change, open an issue first and describe the problem, affected consumers, compatibility impact, and why the capability belongs in this package.

## Development setup

Requirements:

- Python 3.12 or newer;
- `uv`;
- Docker with Compose for live PostgreSQL/PostGIS and Redis checks.

```bash
uv sync --all-extras --locked
docker compose up -d --wait
uv run prodkit-storage upgrade head
uv run prodkit-storage doctor
```

The development database and Redis services bind to loopback only.

## Branches and commits

Do not commit directly to `main`. Use a focused branch and pull request.

Use Conventional Commits as defined in [AGENTS.md](AGENTS.md), for example:

```text
fix(outbox): reject stale lease completion
```

Keep commits scoped and never commit secrets, `.env` files, credentials, private keys, production data, or sensitive logs.

## Database and migration changes

Published Alembic revision files are immutable. Never edit, rename, or delete a released migration; add a new revision instead.

New revisions must pass:

```bash
uv run prodkit-storage migration-check path/to/revision.py
```

Prefer expand/backfill/enforce/contract rollouts for risky schema changes. Use the packaged staged migration helpers where appropriate.

`CREATE INDEX CONCURRENTLY` uses Alembic's `autocommit_block()`, which commits preceding migration work. Put concurrent index creation in a dedicated revision rather than mixing it with transactional DDL that must commit atomically.

Resumable backfill checkpoints and mutations must advance in the same transaction. If more than one worker can run a backfill, the application must serialize ownership with a row lock, advisory lock, or equivalent coordination mechanism.

## Validation

At minimum, run the checks relevant to your change. Before requesting merge, the repository CI must be green.

```bash
uv lock
git diff --exit-code -- uv.lock
uv sync --all-extras --locked
uv run ruff check .
uv run mypy
uv run alembic upgrade head --sql > /tmp/migration.sql
uv run alembic upgrade head
uv run alembic check
uv run pytest --cov --cov-report=term-missing
```

For changes touching infrastructure behavior, also exercise the live PostgreSQL/PostGIS and Redis paths. CI additionally performs backup/restore verification, RLS isolation tests, DB/Redis smoke load, bounded dependency-failure checks, downgrade/roll-forward verification, dependency audit, Docker build, Trivy scanning, and SPDX SBOM generation.

Do not weaken a gate merely to make a pull request green. Fix the root cause or document a narrowly reviewed exception.

## Pull requests

A pull request should explain:

- the problem being solved;
- the implementation and important tradeoffs;
- compatibility, migration, security, and operational impact;
- tests and validation performed;
- any remaining limitations or follow-up work.

Keep the PR focused. Review comments should be resolved or explicitly answered before merge. Squash merge is preferred when development history contains diagnostic or iterative fix commits.

## Security vulnerabilities

Do not open a public issue for a suspected vulnerability. Follow the private reporting process in [SECURITY.md](SECURITY.md).

## Support questions

For usage and troubleshooting guidance, see [SUPPORT.md](SUPPORT.md). Please keep issue reports reproducible and remove credentials, private data, and production secrets from examples and logs.
