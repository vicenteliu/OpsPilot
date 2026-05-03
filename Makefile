.PHONY: install install-dev install-ui dev ensure-venv test test-cov test-ollama lint format \
        typecheck validate serve build-ui lint-ui ci-ui ci \
        ollama-up ollama-down ollama-pull ollama-logs harness golden golden-kb docker-build clean help

# Use python3.12 explicitly; on macOS this resolves to brew's installation.
PYTHON ?= python3.12
VENV   ?= .venv
PIP    := $(VENV)/bin/pip
PY     := $(VENV)/bin/python
PYTEST := $(VENV)/bin/pytest
RUFF   := $(VENV)/bin/ruff
MYPY   := $(VENV)/bin/mypy
OPSPL  := $(VENV)/bin/opspilot

PNPM    := pnpm
WEB_DIR := web

help: ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Create venv and install in editable mode with dev extras.
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -U pip
	$(PIP) install -e ".[dev]"
	@echo
	@echo "Done. Activate with: source $(VENV)/bin/activate"

install-dev: ## Install Python deps in editable mode with dev extras.
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -U pip
	$(PIP) install -e ".[dev]"

install-ui: ## Install Svelte/Node dependencies.
	cd $(WEB_DIR) && $(PNPM) install

ensure-venv: ## Fail fast if venv / dev extras not installed.
	@test -x $(PYTEST) || { \
	  echo "venv missing or incomplete at $(VENV)/. Run: make install"; \
	  exit 1; \
	}

test: ensure-venv ## Run unit tests (skip slow / requires_ollama).
	$(PYTEST) tests/ -m "not slow and not requires_ollama"

test-cov: ensure-venv ## Run tests with coverage.
	$(PYTEST) tests/ --cov=opspilot --cov-report=term-missing -m "not slow and not requires_ollama"

test-ollama: ensure-venv ## Run tests that require a running Ollama (assumes `make ollama-up && make ollama-pull`).
	$(PYTEST) tests/ -m "requires_ollama"

lint: ensure-venv ## Run ruff linter.
	$(RUFF) check src/ tests/
	$(RUFF) format --check src/ tests/

format: ensure-venv ## Auto-format with ruff.
	$(RUFF) check --fix src/ tests/
	$(RUFF) format src/ tests/

typecheck: ensure-venv ## Run mypy.
	$(MYPY) src/

validate: ensure-venv ## Validate every example file against its inferred schema.
	$(OPSPL) validate examples/ --recursive

serve: ensure-venv ## Start the FastAPI API server on port 8000.
	$(VENV)/bin/uvicorn opspilot.api.app:app --reload --port 8000

build-ui: install-ui ## Build Svelte app for production.
	cd $(WEB_DIR) && $(PNPM) build

lint-ui: install-ui ## Lint and type-check the Svelte app.
	cd $(WEB_DIR) && $(PNPM) check

ci-ui: lint-ui ## Svelte quality gate (type-check).

dev: ensure-venv install-ui ## Start FastAPI (port 8000) + Svelte dev server (port 5173).
	@echo "Starting API and UI dev servers (Ctrl+C stops both)..."
	@trap 'kill 0' SIGINT; \
	  $(VENV)/bin/uvicorn opspilot.api.app:app --reload --port 8000 & \
	  cd $(WEB_DIR) && $(PNPM) dev; \
	  wait

ci: lint typecheck test validate ## Run the full quality gate.

# ── PR-3: Ollama orchestration ──────────────────────────────────────────
# OLLAMA_MODE = local  → talk to host's `ollama` binary (macOS dev default;
#                        keeps Metal GPU; skip ollama-up/-down).
# OLLAMA_MODE = docker → talk to docker-compose service (CI / Linux server).
OLLAMA_MODE        ?= local
OLLAMA_CHAT_MODEL  ?= gemma4:e4b
OLLAMA_EMBED_MODEL ?= nomic-embed-text-v2-moe

ollama-up: ## Start Ollama (local: verify daemon / docker: compose up).
ifeq ($(OLLAMA_MODE),docker)
	docker compose up -d ollama
	@echo "Ollama starting; check: docker compose ps"
else
	@ollama list >/dev/null 2>&1 && echo "Local Ollama running on :11434" || \
	  { echo "Local Ollama not running. Start with:"; \
	    echo "  brew services start ollama   # or: ollama serve &"; \
	    exit 1; }
endif

ollama-down: ## Stop Ollama (docker only; for local use brew/launchctl).
ifeq ($(OLLAMA_MODE),docker)
	docker compose down
else
	@echo "Local mode: Make does not manage host daemons."
	@echo "Stop with: brew services stop ollama"
endif

ollama-pull: ## Pull default chat + embed models (override via OLLAMA_CHAT_MODEL/_EMBED_MODEL).
ifeq ($(OLLAMA_MODE),docker)
	docker compose exec ollama ollama pull $(OLLAMA_CHAT_MODEL)
	docker compose exec ollama ollama pull $(OLLAMA_EMBED_MODEL)
else
	ollama pull $(OLLAMA_CHAT_MODEL)
	ollama pull $(OLLAMA_EMBED_MODEL)
endif

ollama-logs: ## Tail Ollama logs.
ifeq ($(OLLAMA_MODE),docker)
	docker compose logs -f ollama
else
	@echo "Local mode: tail logs from the host:"
	@echo "  tail -f ~/.ollama/logs/server.log         # macOS"
	@echo "  log stream --predicate 'process == \"ollama\"'   # macOS Console"
endif

# ── PR-8: Harness + Docker ──────────────────────────────────────────────

harness: ensure-venv ## Run a single fixture through the harness (pass --fixture/--golden/--playbook).
	$(OPSPL) harness run --fixture $(FIXTURE) --golden $(GOLDEN) --playbook $(PLAYBOOK) --output $(or $(OUTPUT),results.jsonl)

golden-kb: ensure-venv ## Load the Stage 1 spec example KB (frozen fixture, deterministic ids).
	$(OPSPL) kb load-fixture \
	    --doc-meta examples/scn_ticket_summary_zh/kb/doc-meta.json \
	    --chunks   examples/scn_ticket_summary_zh/kb/chunks.jsonl

golden: ensure-venv golden-kb ## Run the Stage 1 golden test (auto-ingests KB; needs Ollama running).
	$(OPSPL) harness golden --output golden-results.jsonl

docker-build: ## Build the multi-stage docker image (opspilot:latest).
	docker build -t opspilot:latest .
	docker run --rm opspilot:latest opspilot --version

clean: ## Remove venv + caches.
	rm -rf $(VENV) .pytest_cache .ruff_cache .mypy_cache
	rm -rf build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
