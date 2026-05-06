---
doc_id: doc_e5f6a7b8
title: AWS IAM Permission Error Troubleshooting SOP
valid_from: 2026-02-01
source_authority: official
---

# AWS IAM Permission Error Troubleshooting SOP

> Scope: AWS IAM identity-based and resource-based policies. Covers AccessDenied and UnauthorizedOperation errors. Does not cover SCP (Service Control Policies) without AWS Organizations access.

## 1. Common Error Codes

| Error Code | Trigger | Likely Root Cause |
|---|---|---|
| AccessDenied | API call rejected | Missing Allow, explicit Deny in identity/resource policy |
| UnauthorizedOperation | EC2/S3 control-plane | IAM role lacks the EC2/S3 action in its policy |
| InvalidClientTokenId | Credential used | Access key deactivated or deleted |
| ExpiredTokenException | Assumed role token | STS token TTL expired; re-assume role |
| NoCredentialProviders | SDK init | Missing env vars, missing instance profile, no ~/.aws/credentials |

## 2. Diagnosis Steps

1. **Read the full error**: The `AccessDenied` message usually contains the ARN of the principal, the action, and the resource. Copy all three.
2. **Simulate the call**: Use IAM Policy Simulator (`aws iam simulate-principal-policy`) to replay the denied API call with the exact resource ARN.
3. **Check effective policies**:
   - Identity-based: `aws iam list-attached-role-policies --role-name <role>` + `aws iam get-policy-version`
   - Resource-based (S3, KMS, SQS): `aws s3api get-bucket-policy --bucket <name>`
   - Condition keys: Look for `aws:RequestedRegion`, `aws:SourceIP`, or `aws:MultiFactorAuthPresent` conditions that may silently deny.
4. **Check SCPs** (if AWS Organizations): `aws organizations list-policies-for-target --target-id <account-id> --filter SERVICE_CONTROL_POLICY`
5. **Verify credential chain**: Print resolved identity `aws sts get-caller-identity` — confirm the expected role/user is active.

## 3. Remediation

### 3.1 Add Missing Permission

1. Identify the exact action from the error (`iam:PassRole`, `s3:GetObject`, etc.).
2. Open IAM Console → locate the role → attach an inline or managed policy with the minimum required `Allow` statement.
3. Re-run the failing operation within 60 seconds (policy propagation).
4. If blocked by an explicit `Deny`, find and remove/condition the deny statement before adding the Allow.

### 3.2 Rotate Expired Credentials

1. `aws iam create-access-key --user-name <user>` — create a new key.
2. Update the key in the application config or Secrets Manager.
3. `aws iam delete-access-key --access-key-id <old-key> --user-name <user>` — deactivate the old key after confirming the new one works.

**Escalation criteria**: SCP-level deny confirmed → escalate to AWS Account Owner (requires Organizations management account access).
