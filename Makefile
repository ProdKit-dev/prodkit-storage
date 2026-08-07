.PHONY: install up down migrate doctor test integration lint typecheck check clean

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

check: lint typecheck test

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov dist build
