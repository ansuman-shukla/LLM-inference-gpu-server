VENV := .venv
ENV_FILE := .env
UV := uv
UV_RUN := $(UV) run --env-file $(ENV_FILE)

.PHONY: install venv env dev format-check lint format test-unit test-integration test smoke-import ci migrate run-api run-worker run-recovery run-flusher run-vllm wait-vllm smoke bench

env: $(ENV_FILE)

$(ENV_FILE):
	cp .env.example $(ENV_FILE)

venv: $(VENV)/bin/python

$(VENV)/bin/python:
	$(UV) venv $(VENV)

install: env venv
	$(UV) sync --all-groups

dev: env venv
	$(UV_RUN) uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

format-check: env venv
	$(UV_RUN) ruff format --check backend tests

lint: env venv
	$(UV_RUN) ruff check backend tests
	$(UV_RUN) mypy backend

format: env venv
	$(UV_RUN) ruff format backend tests
	$(UV_RUN) ruff check backend tests --fix

test-unit: env venv
	$(UV_RUN) pytest tests/unit -q

test-integration: env venv
	$(UV_RUN) pytest tests/integration -q

test: env venv
	$(UV_RUN) pytest tests -q

smoke-import: env venv
	$(UV_RUN) python -c "from backend.main import app; assert app.title == 'GPU Inference Backend'"

ci: format-check lint test-unit smoke-import

migrate: env venv
	$(UV_RUN) alembic upgrade head

run-api: env venv
	$(UV_RUN) uvicorn backend.main:app --host 127.0.0.1 --port 8000

run-worker: env venv
	$(UV_RUN) python -m backend.workers.batch_worker

run-recovery: env venv
	$(UV_RUN) python -m backend.workers.recovery_scanner

run-flusher: env venv
	$(UV_RUN) python -m backend.workers.analytics_flusher

run-vllm: env venv
	$(UV_RUN) python -m backend.scripts.run_vllm

wait-vllm: env venv
	$(UV_RUN) python -m backend.scripts.wait_for_vllm

run-redis: env venv
	$(UV_RUN) python -m backend.scripts.run_redis

smoke: env venv
	$(UV_RUN) python -m backend.scripts.smoke_test

bench: env venv
	$(UV_RUN) python -m backend.scripts.benchmark
