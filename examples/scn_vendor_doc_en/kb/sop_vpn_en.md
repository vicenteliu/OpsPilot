---
title: "VPN Troubleshooting SOP (English)"
language: en
source_authority: official
valid_from: 2026-01-01
tags: [vpn, sop, ipsec, ikev2, vendor]
---

# VPN Troubleshooting SOP

> Scope: Enterprise IPSec / IKEv2 VPN. Does not cover SSL VPN.

## 1. Symptom Classification

Use client-side error messages and log keywords to identify the failure category:

| Symptom | Keywords | Likely Root Cause |
|---|---|---|
| Authentication failure | `authentication failed`, `peer auth failed`, `IKE_SA_INIT failed` | Auth backend / credentials / time drift |
| Tunnel establishment failure | `IKE timeout`, `UDP 500/4500 dropped` | Network / firewall / NAT |
| Connected but slow | latency > 200ms, throughput < 1 Mbps | MTU / congestion / server load |

## 2. Troubleshooting Procedure

### 2.1 Authentication Errors

When multiple users fail authentication simultaneously, the issue is almost always server-side.

1. **Collect client logs**: `grep -E "auth|fail" vpn-client.log` — determine whether the error is `peer authentication failed` (server rejects) or `local auth failed` (client-side).
2. **Verify auth backend health**: Confirm RADIUS (ports 1812/1813) and AD LDAP (ports 389/636) are reachable. Check for recent change windows.
3. **Test with known-good credentials**: Attempt login via the VPN gateway management console using a test account. If it also fails, the issue is service-wide.
4. **Verify time synchronization**: Certificate validation is time-sensitive. Server: `chronyc tracking`; client: `ntpq -p`. A drift > 30 seconds causes authentication failures.

**Escalation criteria**: Multiple users affected + no authentication records in server logs → escalate to L2 Network Team.

### 2.2 Tunnel Establishment Failures

1. End-to-end reachability: `nc -vzu <vpn_gw> 500` and `nc -vzu <vpn_gw> 4500`
2. ESP (IP protocol 50) blocked by NAT device: NAT-T must be enabled
3. MTU discovery: `ping -M do -s 1400 <vpn_gw>` — reduce to 1200 if necessary

## 3. Escalation Policy

| Condition | Escalation Target |
|---|---|
| Multiple users affected + no server-side auth records | L2 Network Team |
| Single user, persistent failure, client can be reinstalled | L2 Endpoint Team |
| Certificate expiry or CA change involved | L3 Security Team |

## 4. Related Resources

- SSL VPN Troubleshooting SOP: `doc_ssl_vpn`
- Network Change Window SOP: `doc_net_change`
