# OpsPilot Stage 1 image — multi-stage Python 3.12 build
# ---------------------------------------------------------------
# Builder stage: install build deps + compile/cache wheels.
# Runtime stage: slim image with just the package + runtime deps.
#
# Build:   docker build -t opspilot:latest .
# Verify:  docker run --rm opspilot:latest opspilot --version
# CI:      pair with `make OLLAMA_MODE=docker ollama-up` for a fully
#          containerised PR-8 golden run.

# ---------------------------------------------------------------
# Web build stage: compile the SvelteKit UI to static files so the
# all-in-one image can serve the login + admin pages (ADR-0020).
FROM node:20-slim AS webbuilder

WORKDIR /web
RUN npm install -g pnpm@10
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

# ---------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

# System deps for lancedb + httpx; libstdc++ pulled by base image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Install dependencies first so `pip install -e .` later is fast.
COPY pyproject.toml ./
# hatchling reads README.md for the package's long-description metadata.
COPY README.md ./
COPY src ./src
COPY docs/specs/memory/storage/sqlite-schema.sql ./docs/specs/memory/storage/sqlite-schema.sql

RUN pip install --upgrade pip \
    && pip wheel --wheel-dir /wheels -e .

# ---------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# Runtime deps only.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user.
RUN useradd --create-home --uid 1001 opspilot
USER opspilot
WORKDIR /home/opspilot

# Install the wheels from the builder. They live under the user's home so the
# non-root user can install and then delete them (removing a dir needs write
# on its parent, and / is root-owned).
COPY --from=builder --chown=opspilot:opspilot /wheels ./wheels
RUN pip install --no-index --find-links=./wheels --user opspilot \
    && rm -rf ./wheels

# Copy spec dirs the runtime needs (sqlite schema + json schemas
# discovered by opspilot.schemas). Specs live under docs/specs/.
COPY --chown=opspilot:opspilot docs/specs ./docs/specs
COPY --chown=opspilot:opspilot playbooks ./playbooks
COPY --chown=opspilot:opspilot examples ./examples

# Built web UI (login + admin + app), served by FastAPI (all-in-one, ADR-0020).
COPY --from=webbuilder --chown=opspilot:opspilot /web/build ./web/build

# Pre-create the state dir owned by the non-root user, so a named volume
# mounted here inherits opspilot ownership instead of Docker's root default
# (otherwise the app can't create kb/ on first start).
RUN mkdir -p /home/opspilot/.opspilot

ENV PATH="/home/opspilot/.local/bin:${PATH}"
ENV LANCEDB_CONFIG_DIR="/home/opspilot/.config/lancedb"
ENV OPSPILOT_HOME="/home/opspilot/.opspilot"
# The package resolves its spec schemas relative to the repo root in dev; when
# pip-installed here it reads them from the shipped copy via this override.
ENV OPSPILOT_SPECS_DIR="/home/opspilot/docs/specs"
# FastAPI serves the UI from here (opspilot.api.app._mount_ui).
ENV OPSPILOT_UI_DIR="/home/opspilot/web/build"

# Default: print version + help so `docker run opspilot` is non-interactive.
# All-in-one workbench:
#   docker run -p 8000:8000 \
#     -e OPSPILOT_BOOTSTRAP_ADMIN=admin -e OPSPILOT_BOOTSTRAP_PASSWORD=... \
#     -e OPSPILOT_API_TOKEN=$(openssl rand -hex 32) \
#     opspilot serve --host 0.0.0.0 --port 8000
ENTRYPOINT ["opspilot"]
CMD ["--help"]
