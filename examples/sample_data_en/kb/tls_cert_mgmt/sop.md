---
doc_id: doc_f3a4b5c6
title: TLS Certificate Management SOP
valid_from: 2026-03-01
source_authority: official
---

# TLS Certificate Management SOP

> Scope: Public-facing HTTPS services using certificates issued by Let's Encrypt, DigiCert, or internal CA. Covers renewal, rotation, and emergency replacement. Does not cover client certificates (mTLS).

## 1. Certificate Lifecycle

Certificates follow a standard lifecycle. Monitor expiry proactively to avoid outages:

| Phase | Timeline | Action |
|---|---|---|
| Issuance | Day 0 | CA signs CSR; install cert + intermediate chain |
| Monitoring | Day 1 – Day 60 | Automated expiry check (alert at 30-day threshold) |
| Renewal window | 30 days before expiry | Initiate renewal; test on staging before prod swap |
| Emergency rotation | Any time | Cert compromised or CA distrust event |
| Revocation | After rotation | Submit CRL/OCSP revocation to CA |

**Key file locations**:
- Cert: `/etc/ssl/certs/<domain>.pem`
- Key: `/etc/ssl/private/<domain>.key` (mode 0600, root-owned)
- Chain: `/etc/ssl/certs/<domain>-chain.pem`
- NGINX snippet: `/etc/nginx/snippets/ssl-<domain>.conf`

## 2. Renewal Procedure

### 2.1 Let's Encrypt (Certbot)

1. **Dry-run first**: `certbot renew --dry-run --cert-name <domain>` — confirm no DNS/HTTP-01 challenge failures.
2. **Renew**: `certbot renew --cert-name <domain>` — Certbot writes the new cert and restarts the configured hook.
3. **Verify**: `openssl x509 -noout -dates -in /etc/letsencrypt/live/<domain>/cert.pem` — confirm `notAfter` is > 60 days out.
4. **Reload web server**: `systemctl reload nginx` (Certbot deploy hook should do this automatically).

### 2.2 DigiCert / Internal CA

1. Generate CSR: `openssl req -new -key <domain>.key -out <domain>.csr -subj "/CN=<domain>/O=Acme Corp"`.
2. Submit CSR to CA portal or internal ACME endpoint.
3. Download signed cert + intermediate chain from CA.
4. Test on staging: copy cert + key, reload nginx, validate with `curl -vI https://<staging-domain>`.
5. Deploy to production: atomic swap via symlink — `ln -sfn /etc/ssl/certs/<domain>-new.pem /etc/ssl/certs/<domain>.pem`.
6. Reload nginx and verify: `echo | openssl s_client -connect <domain>:443 2>/dev/null | openssl x509 -noout -dates`.

## 3. Emergency Rotation

Use when a private key is compromised or a CA distrust event occurs:

1. **Revoke immediately**: Submit revocation request to CA (DigiCert portal, Let's Encrypt `certbot revoke`, or internal CA API).
2. **Generate a new key pair**: `openssl genrsa -out <domain>-new.key 4096` — do NOT reuse the compromised key.
3. **Issue replacement cert** using the new CSR (follow §2 procedure with priority flag if using DigiCert).
4. **Deploy within 1 hour**: Update load balancer / CDN origin certificate. Document in incident ticket.
5. **Audit access logs**: Check who downloaded or accessed the compromised key file in the 30 days prior.
6. **Notify Security Team**: Submit a key compromise report within 4 hours of discovery.

**Escalation criteria**: CA revokes trust for your root → escalate to Security Team for cross-signed alternative or CA migration.
