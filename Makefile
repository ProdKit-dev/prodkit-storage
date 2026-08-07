.PHONY: install up down migrate schema-check doctor test integration lint typecheck security backup-check load-smoke check clean

install:
	uv sync --all-extras

up:
	docker compose up -d --wait

down:
	docker compose down

migrate:
	uv run prodkit-storage upgrade head

schema-check:
	uv run prodkit-storage schema-check

doctor:
	uv run prodkit-storage doctor

test:
	uv run pytest -m "not integration"

integration:
	uv run pytest -m integration

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy

security:
	uv run pip-audit
	docker build --tag prodkit-storage:local .
	docker run --rm aquasec/trivy:latest image \
		--exit-code 1 --ignore-unfixed --severity HIGH,CRITICAL \
		prodkit-storage:local

backup-check:
	uv run python ops/backup/verify_postgres_backup.py \
		--database-url "$${PRODKIT_STORAGE_DATABASE_URL:-postgresql://prodkit:prodkit@127.0.0.1:5432/prodkit}"

load-smoke:
	uv run python ops/load/storage_smoke.py --iterations 100 --concurrency 10

check: lint typecheck test

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov dist build
