.PHONY: install up down migrate doctor test integration lint typecheck security check clean

install:
	uv sync --all-extras

up:
	docker compose up -d --wait

down:
	docker compose down

migrate:
	uv run prodkit-storage upgrade head

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

check: lint typecheck test

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov dist build
