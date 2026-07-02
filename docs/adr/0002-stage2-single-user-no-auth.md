# Stage 2 WebUI: single-user local deployment, no authentication

Status: superseded by [ADR-0011](0011-remote-access-bearer-token-proxy-tls.md) — the *no-auth / local-only* part. The single-user model itself still stands.

OpsPilot Stage 2 targets IT practitioners running the tool on their own machine. We deliberately omitted authentication and multi-tenancy: there is one user, one config file, and no shared session state. "Module toggle" (which UI features are visible) is driven by `ui.modules` in `~/.opspilot/config.yaml`, not by identity or roles.

## Consequences

- Adding multi-user support later requires introducing an auth layer, session ownership model, and per-user config — a meaningful refactor. This is acceptable because the product positioning is explicitly a local workbench, not a SaaS.
- `ui.modules` toggling is a config-file restart, not a runtime permission system. Users who want to hide `ingest` from the UI edit the yaml and restart the server.
