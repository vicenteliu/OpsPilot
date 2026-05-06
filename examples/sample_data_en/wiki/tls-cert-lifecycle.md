---
page_id: "wpg_f3a4b5c6"
slug: "tls-cert-lifecycle"
kind: "entity"
title: "TLS Certificate Lifecycle"
summary: "End-to-end lifecycle of production TLS certificates: issuance, monitoring, renewal via Certbot/DigiCert, and emergency rotation on key compromise."
namespace: "opspilot:public-kb"
classification: "internal"
language: "en"
version: "1.0.0"
created_at: "2026-05-06T10:00:00Z"
updated_at: "2026-05-06T10:00:00Z"

tags: ["tls", "ssl", "certificates", "security", "letsencrypt", "certbot"]
aliases: ["certificate management", "TLS renewal", "SSL cert rotation"]

derived_from:
  sources:
    - kind: "kb_document"
      ref: "doc_f3a4b5c6"
      sha256: "sha256:f3a4b5c6f3a4b5c6f3a4b5c6f3a4b5c6f3a4b5c6f3a4b5c6f3a4b5c6f3a4b5c6"
      line_start: 8
      line_end: 59
  parent_pages: []

outbound_links: []
inbound_link_count: 0

redacted: true
redaction_rules_version: "1.0.0"

lifecycle_state: "live"
owner: "security-team@example.com"
collaborators: []

kb_registration:
  kb_doc_id: null
  registered_at: null
  embedding_model: null
  chunk_count: null

lint_state:
  last_linted_at: null
  open_issue_ids: []

extensions:
  entity:
    related_entities:
      - "k8s-cluster-prod"
    related_concepts:
      - "oncall-escalation-matrix"
---

# TLS Certificate Lifecycle

## What is it

The policy and procedure governing TLS certificates for all public-facing HTTPS services. Covers two CA paths: **Let's Encrypt** (automated via Certbot) and **DigiCert / Internal CA** (manual CSR workflow).

## Lifecycle Phases

| Phase | Timeline | Owner | Alert Threshold |
|---|---|---|---|
| Issuance | Day 0 | Security Team | — |
| Monitoring | Ongoing | Automated (Prometheus) | 30 days to expiry |
| Renewal | 30 days before expiry | Security / Platform | 14 days = critical |
| Emergency rotation | On compromise | Security Team | Immediate |
| Revocation | After rotation | Security Team | Within 24 h |

## Renewal Quick Reference

**Let's Encrypt**:
```bash
certbot renew --dry-run --cert-name <domain>   # test
certbot renew --cert-name <domain>              # execute
openssl x509 -noout -dates -in /etc/letsencrypt/live/<domain>/cert.pem
systemctl reload nginx
```

**DigiCert / Internal CA**: Generate CSR → submit to portal → install cert + chain → atomic symlink swap → verify with `openssl s_client`.

## Emergency Rotation Checklist

1. Revoke old cert at CA
2. Generate new key pair (never reuse compromised key)
3. Issue replacement cert (priority flag on DigiCert)
4. Deploy within 1 hour
5. Audit who accessed the old key
6. File key compromise report to Security Team within 4 hours

## File Locations

| File | Path | Permissions |
|---|---|---|
| Certificate | `/etc/ssl/certs/<domain>.pem` | 0644 |
| Private key | `/etc/ssl/private/<domain>.key` | 0600 root |
| Chain | `/etc/ssl/certs/<domain>-chain.pem` | 0644 |

## Related

- depends_on → [[oncall-escalation-matrix]]: CA distrust events are P0 incidents

## Sources

1. [TLS Certificate Management SOP](examples/sample_data_en/kb/tls_cert_mgmt/sop.md:8-59)

## Changelog

- v1.0.0 (2026-05-06): initial; derived from doc_f3a4b5c6
