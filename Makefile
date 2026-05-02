.PHONY: install dev test test-cov test-ollama lint format typecheck validate \
        ollama-up ollama-down ollama-pull ollama-logs clean ci help

# Use python3.12 explicitly; on macOS this resolves to brew's installation.
PYTHON ?= python3.12
VENV   ?= .venv
PIP    := $(VENV)/bin/pip
PY     := $(VENV)/bin/python
PYTEST := $(VENV)/bin/pytest
RUFF   := $(VENV)/bin/ruff
MYPY   := $(VENV)/bin/mypy
OPSPL  := $(VENV)/bin/opspilot

help: ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Create venv and install in editable mode with dev extras.
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -U pip
	$(PIP) install -e ".[dev]"
	@echo
	@echo "Done. Activate with: source $(VENV)/bin/activate"

dev: install ## Alias for install.

test: ## Run unit tests (skip slow / requires_ollama).
	$(PYTEST) tests/ -m "not slow and not requires_ollama"

test-cov: ## Run tests with coverage.
	$(PYTEST) tests/ --cov=opspilot --cov-report=term-missing -m "not slow and not requires_ollama"

test-ollama: ## Run tests that require a running Ollama (assumes `make ollama-up && make ollama-pull`).
	$(PYTEST) tests/ -m "requires_ollama"

lint: ## Run ruff linter.
	$(RUFF) check src/ tests/
	$(RUFF) format --check src/ tests/

format: ## Auto-format with ruff.
	$(RUFF) check --fix src/ tests/
	$(RUFF) format src/ tests/

typecheck: ## Run mypy.
	$(MYPY) src/

validate: ## Validate every example file against its inferred schema.
	$(OPSPL) validate examples/ --recursive

ci: lint typecheck test validate ## Run the full PR-1 quality gate.

# ── PR-3: Ollama orchestration ──────────────────────────────────────────

ollama-up: ## Start Ollama via docker-compose (detached).
	docker compose up -d ollama
	@echo "Ollama starting; check: docker compose ps"

ollama-down: ## Stop Ollama.
	docker compose down

ollama-pull: ## Pull the default Stage 1 chat + embedding models.
	docker compose exec ollama ollama pull qwen2.5:14b-instruct
	docker compose exec ollama ollama pull nomic-embed-text

ollama-logs: ## Tail Ollama logs.
	docker compose logs -f ollama

clean: ## Remove venv + caches.
	rm -rf $(VENV) .pytest_cache .ruff_cache .mypy_cache
	rm -rf build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
