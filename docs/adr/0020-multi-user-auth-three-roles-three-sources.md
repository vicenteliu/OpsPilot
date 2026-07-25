# Multi-user: three fixed roles, three auth sources — supersedes ADR-0002

Status: accepted (2026-07-25)

OpsPilot stops being single-user. The Users are the IT support team
(5–50 people) operating the workbench; end employees are still not Users
— they reach OpsPilot through Channels and the ITSM (ADR-0006 unmoved).
This supersedes ADR-0002 (single-user, no auth) and amends ADR-0011 (the
single bearer token lives on as the **Service token** for machine
callers — Telegram, JSM polling, webhook — authenticating as a `svc:`
identity with operator rights, so every existing adapter keeps working
unchanged).

- **Three fixed roles, not custom RBAC.** `viewer` → `operator` →
  `admin`. A 5–50-person team cannot exercise a permission matrix; three
  levels cover the real cases (new hire / auditor, working engineer,
  owner). Sandbox execution — real shell — is admin-only in v1. Roles
  map from directory groups / OIDC claims with per-User overrides in the
  admin module. Audit upgrades from "the operator did it" to real
  identity: `session.owner` and Asset-event `actor` carry the username.
- **Three auth sources, shipped as three slices.** `local` first
  (bootstrap admin, break-glass when the directory is down — password
  hashes only, never plaintext), then `ldap` (ONE connector for both
  OpenLDAP and Active Directory — they speak the same protocol;
  configurable base DN, user filter, bind template, group attribute),
  then `oidc`. Each slice independently usable and mergeable.
- **OIDC is the only SSO protocol.** Entra ID, Keycloak, Google, Okta,
  Authentik all speak it; AD users have two doors (direct LDAP, or Entra
  OIDC). SAML rejected: XML-signature attack surface, xmlsec dependency
  weight, doubled test matrix — for IdPs that all offer OIDC anyway.
- **Web sessions are server-side + HttpOnly cookie**, revocable at any
  moment; no JWT session tokens at this scale.
- **Secrets never enter the database.** LDAP bind credentials and OIDC
  client secrets are environment-only, like every credential in this
  codebase. The admin module manages people and mappings, shows auth
  source status, and tests connectivity — it does not store secrets.
- **Docker ships as an all-in-one image.** The web UI (login page, admin
  module) joins the api image via a node build stage and is served by
  FastAPI as static files — one `docker run` is a complete workbench.
  ADR-0011's TLS stance is unchanged: reverse proxy remains the
  supported path (the compose nginx stays available), uvicorn `--ssl-*`
  passthrough remains the alternative.

**Rejected:** end-employee logins (thousand-user self-service portal —
different product, and ADR-0006 already gives employees a door);
custom-editable roles (matrix UI and test surface for no gain at this
scale); SAML (above); JWT sessions (revocation pain); secrets in SQLite
(new attack surface against the whole codebase's env-only rule);
keeping the UI out of the image (a permission system without its login
page in the deployment story is not deployable).
