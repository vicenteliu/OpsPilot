# Post-deployment verification

Four integrations are implemented and covered by tests, but **every one of those
tests mocks the counterparty**. Nothing in CI has ever talked to a real
directory server, a real identity provider, or a real WeCom tenant. This file is
the procedure that closes that gap, and it can only be run by someone who has
that infrastructure.

Each check states what it proves *and what it does not* — a green result here is
narrower than it looks, and knowing the edge matters more than the tick.

Record the outcome at the bottom. An unrun check and a passed check must never
look the same.

## 0. Prerequisites

- A deployment reachable at a stable base URL. LDAP works over plain HTTP on a
  private network; **OIDC and WeCom both require public HTTPS** (see
  [deployment.md](deployment.md) for the reverse-proxy setup).
- An admin account you can sign in with. On a fresh volume:

  ```bash
  docker run -d --name opspilot -p 8000:8000 \
    -v opspilot-data:/home/opspilot/.opspilot \
    -e OPSPILOT_BOOTSTRAP_ADMIN=admin \
    -e OPSPILOT_BOOTSTRAP_PASSWORD='<pick one>' \
    -e OPSPILOT_API_TOKEN="$(openssl rand -hex 32)" \
    opspilot:latest serve --host 0.0.0.0 --port 8000
  ```

- Secrets are read from the environment and never stored (see `.env.example`).
  Restart the process after changing any of them.

Throughout, `$BASE` is the public base URL and `$COOKIE` a signed-in admin
session cookie:

```bash
BASE=https://opspilot.example
COOKIE=$(curl -s -c - -X POST "$BASE/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<pw>","source":"local"}' \
  | awk '/opspilot_session/ {print $7}')
```

---

## 1. All-in-one image, first boot

**Status: partially verified.** The image has been built, run, signed into, and
exercised through the UI. What has *not* been done is a **first boot on an empty
volume** — every run so far reused an existing one, so the bootstrap-admin path
and the schema-creation path are untested end to end.

1. `docker volume create opspilot-verify`
2. Start the container against that empty volume with the command in §0.
3. Open `$BASE` in a browser.

**Passes when** the login page renders, the bootstrap admin can sign in, and the
sidebar shows the modules for the admin role.

**Does not prove** anything about upgrades — a first boot exercises schema
creation, not migration of an existing volume.

```bash
docker rm -f opspilot && docker volume rm opspilot-verify   # cleanup
```

---

## 2. LDAP / Active Directory

One connector serves both. The distinguishing setting is the user filter:
`(uid={username})` for OpenLDAP, `(sAMAccountName={username})` for AD.

### Configure

```bash
OPSPILOT_LDAP_URL=ldap://dc.corp.example
OPSPILOT_LDAP_BASE_DN=dc=corp,dc=example
OPSPILOT_LDAP_USER_FILTER=(uid={username})
OPSPILOT_LDAP_BIND_DN=cn=svc-opspilot,ou=svc,dc=corp,dc=example
OPSPILOT_LDAP_BIND_PASSWORD=…
OPSPILOT_LDAP_GROUP_ATTR=memberOf
```

### Checks

**2.1 — the source reports configured**

```bash
curl -s "$BASE/api/admin/auth-status" -H "Cookie: opspilot_session=$COOKIE"
```

Expect `ldap` with `configured: true`. *Proves the env is parsed, nothing more.*

**2.2 — the service account can bind**

```bash
curl -s -X POST "$BASE/api/admin/auth-status/ldap/test" \
  -H "Cookie: opspilot_session=$COOKIE"
```

Expect `ok: true`. **This is the first check that touches the directory.** A
failure here is credentials, network, or TLS — not OpsPilot.

**2.3 — a real directory user can sign in**

```bash
curl -s -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"<directory-user>","password":"<their-pw>","source":"ldap"}'
```

Expect 200 with that username and a role. *Proves user search + bind-as-user.*

**2.4 — group → role mapping actually maps**

Map a group the test user belongs to, then sign in again:

```bash
curl -s -X PUT "$BASE/api/admin/group-roles" \
  -H "Cookie: opspilot_session=$COOKIE" -H 'Content-Type: application/json' \
  -d '{"source":"ldap","group_name":"cn=it-ops,ou=groups,dc=corp,dc=example","role":"operator"}'
```

Expect the role to change from the default to `operator`. **Use the group's
exact DN as the directory returns it in `memberOf`** — a mismatch here silently
falls back to the default role, which looks like the mapping "not working".

**2.5 — a wrong password is refused**

Repeat 2.3 with a bad password; expect 401. *Confirms OpsPilot is not
accepting on bind failure.*

**Does not prove**: referral chasing in multi-domain forests, LDAPS certificate
validation (unless your URL is `ldaps://`), or nested-group resolution — AD
returns only direct `memberOf` unless the filter asks for the recursive form.

---

## 3. OIDC SSO

Authorization code + PKCE. SAML was rejected (ADR-0020).

### Register the app with the IdP

Redirect URI must be **exactly** `$BASE/api/auth/oidc/callback`. Most
"invalid_redirect_uri" failures are a trailing slash or an http/https mismatch.

```bash
OPSPILOT_OIDC_ISSUER=https://login.microsoftonline.com/<tenant>/v2.0
OPSPILOT_OIDC_CLIENT_ID=…
OPSPILOT_OIDC_CLIENT_SECRET=…
OPSPILOT_OIDC_REDIRECT_URL=$BASE/api/auth/oidc/callback
OPSPILOT_OIDC_ROLE_CLAIM=groups
OPSPILOT_OIDC_SCOPES=openid profile email
```

### Checks

**3.1 — discovery works**

```bash
curl -s "$BASE/api/auth/oidc/enabled"
```

Expect enabled. *Proves the issuer's discovery document was fetched — the first
real network call to the IdP.*

**3.2 — the full browser flow**

Open `$BASE/api/auth/oidc/login` in a browser. Expect: redirect to the IdP,
authenticate, land back signed in.

Do this **in a browser, not with curl** — following redirects by hand drops the
PKCE state and will fail in a way that tells you nothing.

**3.3 — the role claim maps**

Map an IdP group to a role via `/api/admin/group-roles` with `source: "oidc"`,
then sign in again and check `GET /api/auth/me`.

If the role does not change, inspect the claim actually issued: Entra emits
group **object ids**, not names, unless the app registration is configured to
emit names. Map whatever the token really contains.

**3.4 — a second sign-in reuses the account**

Sign out and back in. Expect the same username with no duplicate user row in
`/api/admin/users`.

**Does not prove**: token refresh (sessions are server-side cookies, not IdP
tokens), or single logout — signing out of OpsPilot does not sign you out of
the IdP.

---

## 4. WeCom assist mode

The only channel where **WeCom's servers must reach you**, rather than OpsPilot
polling out. Needs a public HTTPS callback.

### Configure

All five are required; with any missing the callback routes stay disabled.

```bash
WECOM_CORP_ID=…
WECOM_AGENT_ID=…
WECOM_APP_SECRET=…
WECOM_CALLBACK_TOKEN=…
WECOM_ENCODING_AES_KEY=…
```

In the app's 接收消息 settings, set the callback URL to
`$BASE/api/channels/wecom/callback`.

### Checks

**4.1 — the URL verification handshake**

Press save in the WeCom admin console. WeCom issues a `GET` with an encrypted
`echostr`; OpsPilot must decrypt and echo it, or the console refuses to save.

**Passes when the console saves.** This is the strongest single check available:
it exercises signature validation and AES decryption against the real
counterparty, which is exactly what the offline tests could only simulate.

**4.2 — a round trip**

Send a message to the app from the WeCom client. Expect an answer a few seconds
later.

The reply arrives through the **active send API**, not as the callback response
— the callback acknowledges immediately and answers out of band. So a fast empty
acknowledgement is correct behaviour, not a failure.

**4.3 — the answer is KB-grounded**

Ask something your KB can answer. Expect citations, confirming the channel is
wired to the same assisted path as the web chat rather than a bare model call.

**Does not prove**: notify mode, which is a separate group-robot webhook —
verify that independently by triggering an intake and watching the group.

---

## Recording the result

Note the date, the version verified, and the outcome per check. A check that was
skipped must be recorded as skipped — the failure mode this file exists to
prevent is an unrun check quietly reading as a passed one.

| Check | Date | Result | Notes |
| --- | --- | --- | --- |
| 1 — all-in-one first boot | | | partially verified; empty-volume boot outstanding |
| 2 — LDAP / AD | | | |
| 3 — OIDC SSO | | | |
| 4 — WeCom assist | | | |
