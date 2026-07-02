# Deployment and configuration

> **Deployment model:** OpsPilot is currently single-user, no-auth, local-only
> by design ([ADR-0002](adr/0002-stage2-single-user-no-auth.md)). Do **not**
> expose the API to the internet — see [SECURITY.md](../SECURITY.md). A
> remote-access foundation (auth + TLS) is on the
> [roadmap](../ROADMAP.md) as the prerequisite for any remote surface
> ([ADR-0010](adr/0010-remote-access-foundation-before-channels.md)).

## Local development

```bash
source .env
opspilot serve --reload --with-ui                 # API + frontend together (Ctrl+C stops both)
opspilot serve --reload                           # API only
opspilot serve --host 0.0.0.0 --workers 2 --json-logs   # production (no frontend)
```

## Docker Compose

```bash
cp .env.example .env   # add API keys
docker compose -f docker-compose.prod.yml up -d
curl http://localhost:8000/health
```

## systemd (Linux)

```bash
sudo cp deploy/systemd/opspilot.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now opspilot
```

See [`deploy/systemd/README.md`](../deploy/systemd/README.md) for full setup
instructions.

## Observability

| Endpoint | Description |
|---|---|
| `GET /health` | Status, version, uptime |
| `GET /metrics` | Prometheus-format counters and histograms |

Structured JSON logging (OTel-compatible) is enabled with `--json-logs`:

```bash
opspilot serve --json-logs 2>&1 | jq .
# {"ts":"2026-05-05T10:00:00Z","severity":"INFO","logger":"opspilot.api","msg":"GET /health 200 1ms"}
```

See [ADR-0007](adr/0007-monitoring-prometheus-client-otel-compatible-logs.md)
for the monitoring stack decision.

## Configuration

All settings live in `~/.opspilot/config.yaml` (optional) or environment
variables. See `.env.example` for the full list.

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Anthropic cloud API key |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `OPENROUTER_API_KEY` | — | OpenRouter API key |
| `GEMINI_API_KEY` | — | Google Gemini API key |
| `OPSPILOT_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama base URL |
| `OPSPILOT_OLLAMA_TIMEOUT_S` | `300` | Ollama request timeout (s). Raise for large local models that are slow to cold-load. |
| `OPSPILOT_HOME` | `~/.opspilot` | State directory (KB, sessions, audit) |
