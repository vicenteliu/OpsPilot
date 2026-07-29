# Deployment and configuration

> **Deployment model:** OpsPilot is multi-user — the IT team signs in, with
> three fixed roles and local / LDAP / OIDC identity sources
> ([ADR-0020](adr/0020-multi-user-auth-three-roles-three-sources.md)). Machine
> callers keep using the Service token. Local (loopback) use needs no
> configuration; remote access requires TLS and a configured identity — see
> [Remote access](#remote-access) below and
> [ADR-0011](adr/0011-remote-access-bearer-token-proxy-tls.md).
>
> Before trusting an LDAP, OIDC or WeCom deployment, run
> [the post-deployment verification checklist](verification.md) — those
> integrations' automated tests all mock the counterparty.

## Local development

```bash
source .env
opspilot serve --reload --with-ui                 # API + frontend together (Ctrl+C stops both)
opspilot serve --reload                           # API only
opspilot serve --host 0.0.0.0 --workers 2 --json-logs   # production (no frontend)
```

## Remote access

Binding beyond loopback is **fail-closed**: `opspilot serve --host 0.0.0.0`
refuses to start unless an API token is configured.

```bash
# 1. Generate and set a token (env or ~/.opspilot/config.yaml api_token)
export OPSPILOT_API_TOKEN="$(openssl rand -hex 32)"

# 2. Serve beyond loopback
opspilot serve --host 0.0.0.0 --port 8001
```

Every endpoint except `/health` then requires `Authorization: Bearer <token>`
(the web UI has a token field in the sidebar; it is stored in localStorage):

```bash
curl -H "Authorization: Bearer $OPSPILOT_API_TOKEN" https://ops.example.com/api/config
```

### TLS

Terminate TLS at a reverse proxy — the supported path:

```caddy
# Caddyfile — automatic Let's Encrypt
ops.example.com {
    reverse_proxy 127.0.0.1:8001
}
```

For nginx, add a standard TLS server block in front of `127.0.0.1:8001`
(see [`deploy/`](../deploy/) for the base config). For direct exposure
without a proxy, uvicorn's TLS flags are passed through:

```bash
opspilot serve --host 0.0.0.0 --ssl-certfile cert.pem --ssl-keyfile key.pem
```

## All-in-one Docker image

The image bundles the built web UI (login + admin + workbench), served by
FastAPI — one container is a complete, login-gated deployment (ADR-0020):

```bash
docker build -t opspilot:latest .
docker run -p 8000:8000 \
  -e OPSPILOT_API_TOKEN="$(openssl rand -hex 32)" \
  -e OPSPILOT_BOOTSTRAP_ADMIN=admin \
  -e OPSPILOT_BOOTSTRAP_PASSWORD='<a-strong-password>' \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -v opspilot-data:/home/opspilot/.opspilot \
  opspilot:latest serve --host 0.0.0.0 --port 8000
# open http://localhost:8000 → sign in as the bootstrap admin
```

Binding beyond loopback stays **fail-closed** (ADR-0011): `--host 0.0.0.0`
refuses to start without `OPSPILOT_API_TOKEN` (which doubles as the Service
token for channel/source adapters). Put TLS in front with a reverse proxy,
or use `--ssl-certfile`/`--ssl-keyfile`. Remove the bootstrap-admin vars
once the account exists.

## Docker Compose

For a multi-service setup (dedicated Ollama, nginx TLS termination):

```bash
cp .env.example .env.prod   # the compose file reads .env.prod, not .env
docker compose -f docker-compose.prod.yml up -d
curl http://localhost/health   # nginx on :80 — the API is internal-only
```

`.env.prod` must set `OPSPILOT_API_TOKEN` (the api service binds `0.0.0.0`,
which is fail-closed without one) plus your provider keys, and
`OPSPILOT_BOOTSTRAP_ADMIN` / `OPSPILOT_BOOTSTRAP_PASSWORD` for the first
sign-in. `OPSPILOT_HOME` and the Ollama URL are set by the compose file —
leave them commented out.

Ollama is **optional** — embeddings default to OpenAI, so the stack above
runs on `OPENAI_API_KEY` alone. Start it only if you want local embeddings or
local chat models:

```bash
docker compose -f docker-compose.prod.yml --profile ollama up -d
docker compose -f docker-compose.prod.yml exec ollama ollama pull nomic-embed-text-v2-moe
# then set OPSPILOT_EMBED_PROVIDER=ollama in .env.prod and restart the api
```

Switching embedders on an existing KB is refused at startup rather than
silently degrading retrieval — see [Embeddings](#embeddings) below.

## systemd (Linux)

```bash
sudo cp deploy/systemd/opspilot.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now opspilot
```

See [`deploy/systemd/README.md`](../deploy/systemd/README.md) for full setup
instructions.

## Embeddings

OpenAI is the default embedder; Ollama is opt-in. With
`OPSPILOT_EMBED_PROVIDER` unset, a configured `OPENAI_API_KEY` selects OpenAI
and its absence falls back to a local Ollama:

| `OPSPILOT_EMBED_PROVIDER` | `OPENAI_API_KEY` | Active embedder |
|---|---|---|
| unset | set | `openai/text-embedding-3-small` |
| unset | — | local Ollama, with a notice in the UI |
| `openai` | set | `openai/text-embedding-3-small` |
| `openai` | — | none — embedding calls fail with the reason |
| `ollama` | either | local Ollama (an explicit choice is never overridden) |

An explicit choice is honoured even when it cannot be served: asking for
Ollama and finding it down does **not** fall through to OpenAI. The two
produce incomparable vectors, so a silent swap would poison the KB rather
than degrade it.

For the same reason the server **refuses to start** against a KB built by a
different embedder. Both defaults are 768-dimensional, so nothing else would
catch it — retrieval would simply return noise:

```
LanceDB table 'chunks' at ~/.opspilot/kb/lancedb was built with embedding
model 'ollama-local/nomic-embed-text-v2-moe@2026-04', but the active embedder
is 'openai/text-embedding-3-small'. Vectors from different embedders are not
comparable, so retrieval would return noise instead of failing. Re-ingest the
KB under the current embedder, or set OPSPILOT_ALLOW_EMBED_MISMATCH=1 to open
it anyway.
```

Re-ingesting is the correct fix. `OPSPILOT_ALLOW_EMBED_MISMATCH=1` exists for
the case where you know the vectors are in fact comparable; it does not make
a mixed KB searchable.

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
| `OPSPILOT_EMBED_PROVIDER` | — | `openai` / `ollama`. Unset: OpenAI if a key is set, else Ollama. See [Embeddings](#embeddings). |
| `OPSPILOT_OPENAI_EMBED_MODEL` | `text-embedding-3-small` | OpenAI embedding model, requested at 768-dim |
| `OPSPILOT_ALLOW_EMBED_MISMATCH` | — | `1` opens a KB built by a different embedder instead of refusing |
| `OPSPILOT_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama base URL |
| `OPSPILOT_OLLAMA_TIMEOUT_S` | `300` | Ollama request timeout (s). Raise for large local models that are slow to cold-load. |
| `OPSPILOT_HOME` | `~/.opspilot` | State directory (KB, sessions, audit) |
