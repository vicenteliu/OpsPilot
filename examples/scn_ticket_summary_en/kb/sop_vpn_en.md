---
id: "doc_afe80531"
source_path: "examples/scn_ticket_summary_en/kb/sop_vpn_en.md"
title: "VPN Troubleshooting SOP (English)"
classification: "internal"
content_hash: "sha256:afe80531ad5aca3dab28814d0cead9cb77dada556f18f70a296bff0be818d877"
version: "1.3.0"
ingested_at: "2026-05-01T10:00:00Z"
last_modified: "2026-04-28T08:30:00Z"
language: "en"
tags: ["vpn", "sop", "L1", "ipsec", "ikev2"]
namespace: "opspilot:public-kb-en"
chunk_strategy: "headings_then_size"
chunk_count: 3
embedding_model: "ollama-local/nomic-embed-text@2024-02"
embedding_dim: 768
redaction_passed: true
redaction_rules_version: "1.0.0"
---

# VPN Troubleshooting SOP

> Scope: Corporate IPSec / IKEv2 VPN. SSL VPN is covered separately (see doc_aaaaaaaa).

## 1. Symptom classification

Use the client error and log keywords to triage quickly:

| Symptom | Keywords | Likely cause |
|---|---|---|
| Auth failure | `authentication failed`, `peer auth failed`, `IKE_SA_INIT failed` | Auth backend / wrong password / clock skew |
| Tunnel won't establish | `IKE timeout`, `UDP 500/4500 dropped` | Network layer / firewall / NAT |
| Connected but slow | latency > 200ms, throughput < 1Mbps | MTU / congestion / server load |

## 2. Investigation order

### 2.1 Authentication errors

When several users fail authentication at the same time, the issue is almost always on the **server-side auth chain**, not the endpoint. Verify the server side first:

1. **Read client logs**: `grep -E "auth|fail" vpn-client.log` — distinguish `peer authentication failed` from `local auth failed`.
2. **Backend health**: confirm RADIUS (ports 1812/1813) or AD LDAP (389/636) is reachable; check for recent change windows.
3. **Test login from console**: use a test account in the VPN gateway admin UI to see if it fails the same way.
4. **Time sync**: certificate validation is clock-sensitive. Server `chronyc tracking` / client `ntpq -p`; > 30s skew triggers failures.

Escalation: multiple users affected + no auth records in server logs → escalate to L2 networking team.

### 2.2 Tunnel establishment failure

1. End-to-end reachability: `nc -vzu <vpn_gw> 500` / `nc -vzu <vpn_gw> 4500`.
2. ESP (IP protocol 50) being dropped by NAT devices: NAT-T must be supported.
3. MTU: `ping -M do -s 1400 <vpn_gw>`, decrease until packets pass — usually around 1200.

## 3. Escalation policy

> - Multiple users affected + no auth records on server → L2 networking
> - Single user, persistent failure, client reinstallable → L2 endpoint
> - Certificate expiry / CA change → L3 security

## 4. Related links

- doc_aaaaaaaa: SSL VPN troubleshooting SOP
- doc_bbbbbbbb: Network change-window SOP
