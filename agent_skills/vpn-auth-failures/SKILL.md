---
id: vpn-auth-failures
name: VPN authentication failures
trigger: A user cannot authenticate to the VPN — login rejected, MFA prompt loops, or "authentication failed" errors.
allowed_tools:
  - kb_search
trust: internal
---

# VPN authentication failures

Use this procedure when a user reports they cannot authenticate to the VPN
(credentials rejected, MFA loop, "authentication failed"). Confirm each step
with the user before moving on; suggest actions, never make account changes
without confirmation.

## 1. Scope the problem

- One user or many? Many users → suspect the gateway or directory, not the
  account. Search the KB for recent gateway/incident notes before proceeding.
- Which client and version? Note the OS and VPN client build.
- When did it last work? A sudden break points at an expiry, a password
  change, or a gateway update.

## 2. Check the account

- Is the account locked or disabled in the directory? A recent password
  change that wasn't updated in a saved VPN profile is the most common cause.
- Is the password expired? Have the user sign in to a first-party portal to
  confirm the credentials themselves are valid.

## 3. Check MFA

- If the MFA prompt loops, have the user remove and re-add the VPN entry in
  their authenticator, then retry — the shared secret can drift.
- Confirm the device clock is correct; TOTP fails when the clock is skewed.

## 4. Check the gateway

- Look up the current gateway runbook in the KB (search for the gateway model
  and "authentication"). Confirm the RADIUS / directory connector is healthy.
- If many users are affected and the gateway is implicated, this is an
  Incident — suggest opening one and, if a runbook step calls for it,
  restarting the connector (L2) and notifying affected users (L1).

## 5. Hand off

- If the account and MFA are clean and the gateway is healthy, escalate to
  the network team (L3) with the client version, timestamps, and the exact
  error string.
- Cite the KB runbook chunks you relied on so the engineer can verify.
