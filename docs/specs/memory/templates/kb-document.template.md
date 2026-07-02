---
# Long-term KB document template
# frontmatter fields must conform to schemas/kb-document.schema.json
# the document content (markdown body outside the frontmatter) gets chunked + embedded

id: "doc_e5f6g7h8"
source_path: "playbooks/sop_vpn_zh.md"
source_url: null
title: "VPN Troubleshooting SOP (Chinese)"
classification: "internal"
content_hash: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
version: "1.3.0"
ingested_at: "2026-05-01T10:00:00Z"
last_modified: "2026-04-28T08:30:00Z"
language: "zh-CN"
tags: ["vpn", "sop", "L1", "ipsec"]
namespace: "opspilot:public-kb"

chunk_strategy: "headings_then_size"
chunk_count: 12

embedding_model: "ollama-local/nomic-embed-text@2024-02"
embedding_dim: 768

redaction_passed: true
redaction_rules_version: "1.0.0"

license: null
extensions: {}
---

# VPN Troubleshooting SOP

> Scope: corporate IPSec/IKEv2 VPN; does not cover SSL VPN (see doc_xxxxxxxx)

## 1. Symptom classification

| Symptom | Keywords | Primary suspects |
|---|---|---|
| Authentication failure | `authentication failed`, `peer auth failed`, `IKE_SA_INIT error` | auth backend / user password / clock drift |
| Tunnel fails to establish | `IKE timeout`, `UDP 500/4500 dropped` | network layer / firewall / NAT |
| Extremely slow | connected but latency > 200 ms, throughput < 1 Mbps | MTU / congestion / server load |

## 2. Troubleshooting order

### 2.1 Authentication errors
1. Check the client log: `grep -E "auth|fail" vpn-client.log`
2. Confirm the server side: are RADIUS / AD healthy (ports 1812/1813, LDAP 389/636)
3. Try logging in with `[USERNAME]` on the admin console (never put a real account into the ticket)
4. Clock drift causes certificate validation failures: `ntpq -p` / `chronyc tracking`

### 2.2 Tunnel establishment failure
1. End-to-end connectivity: `nc -vzu <vpn_gw> 500` / `nc -vzu <vpn_gw> 4500`
2. Is ESP (IP protocol 50) being dropped by a NAT device: NAT-T must be supported
3. MTU: `ping -M do -s 1400 <vpn_gw>`, stepping down to 1200 to see whether it gets through

## 3. Escalation policy

> Criteria for escalating to L2:
> - Multiple users affected + no auth records in server logs → L2 network team
> - A single user persistently unable to connect + client can be reinstalled → L2 endpoint team

## 4. Related links

- doc_aaaaaaaa: SSL VPN troubleshooting SOP
- doc_bbbbbbbb: network change-window SOP
