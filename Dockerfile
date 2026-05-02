# OpsPilot Stage 1 image — multi-stage Python 3.12 build
# ---------------------------------------------------------------
# Builder stage: install build deps + compile/cache wheels.
# Runtime stage: slim image with just the package + runtime deps.
#
# Build:   docker build -t opspilot:latest .
# Verify:  docker run --rm opspilot:latest opspilot --version
# CI:      pair with `make OLLAMA_MODE=docker ollama-up` for a fully
#          containerised PR-8 golden run.

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
COPY src ./src
COPY memory/storage/sqlite-schema.sql ./memory/storage/sqlite-schema.sql

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

# Install the wheels from the builder.
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels --user opspilot \
    && rm -rf /wheels

# Copy spec dirs the runtime needs (sqlite schema + json schemas
# discovered by opspilot.schemas).
COPY --chown=opspilot:opspilot memory ./memory
COPY --chown=opspilot:opspilot session ./session
COPY --chown=opspilot:opspilot harness ./harness
COPY --chown=opspilot:opspilot orchestrator ./orchestrator
COPY --chown=opspilot:opspilot providers ./providers
COPY --chown=opspilot:opspilot skills ./skills
COPY --chown=opspilot:opspilot wiki ./wiki
COPY --chown=opspilot:opspilot sandbox ./sandbox
COPY --chown=opspilot:opspilot playbooks ./playbooks
COPY --chown=opspilot:opspilot examples ./examples

ENV PATH="/home/opspilot/.local/bin:${PATH}"
ENV LANCEDB_CONFIG_DIR="/home/opspilot/.config/lancedb"
ENV OPSPILOT_HOME="/home/opspilot/.opspilot"

# Default: print version + help so `docker run opspilot` is non-interactive.
ENTRYPOINT ["opspilot"]
CMD ["--help"]
