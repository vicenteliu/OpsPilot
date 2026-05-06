---
page_id: "wpg_c9d0e1f2"
slug: "aws-iam-common-errors"
kind: "summary"
title: "AWS IAM Common Errors Summary"
summary: "Quick-reference summary of the five most frequent AWS IAM error codes, their triggers, and the first remediation step for each."
namespace: "opspilot:public-kb"
classification: "internal"
language: "en"
version: "1.0.0"
created_at: "2026-05-06T10:00:00Z"
updated_at: "2026-05-06T10:00:00Z"

tags: ["aws", "iam", "accessdenied", "cloud", "security", "summary"]
aliases: ["IAM errors", "AccessDenied AWS", "AWS permission errors"]

derived_from:
  sources:
    - kind: "kb_document"
      ref: "doc_e5f6a7b8"
      sha256: "sha256:e5f6a7b8e5f6a7b8e5f6a7b8e5f6a7b8e5f6a7b8e5f6a7b8e5f6a7b8e5f6a7b8"
      line_start: 8
      line_end: 21
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
  summary:
    source_doc_id: "doc_e5f6a7b8"
    source_uri: null
---

# AWS IAM Common Errors Summary

## Source

Derived from the AWS IAM Permission Error Troubleshooting SOP (`doc_e5f6a7b8`). See that document for full diagnosis steps.

## Error Quick Reference

| Error | Meaning | First Action |
|---|---|---|
| `AccessDenied` | Policy has no matching Allow, or has explicit Deny | Run `aws iam simulate-principal-policy` with the exact ARN |
| `UnauthorizedOperation` | EC2/S3 control-plane action not in role policy | Attach missing action to role inline policy |
| `InvalidClientTokenId` | Access key deactivated or deleted | Rotate credentials; check `aws iam list-access-keys` |
| `ExpiredTokenException` | STS assumed-role token past TTL | Re-assume the role; check `aws sts get-caller-identity` |
| `NoCredentialProviders` | SDK cannot find any credentials | Check env vars, instance profile, or `~/.aws/credentials` |

## Decision Tree

```
AccessDenied?
├── Principal ARN = expected role?  → NO → wrong credentials; rotate
└── YES
    ├── Explicit Deny in policy?   → YES → remove/condition the Deny
    └── NO
        └── SCP blocking?          → YES → escalate to AWS Account Owner
                                   → NO  → add Allow for the action
```

## Key Commands

```bash
# Who am I?
aws sts get-caller-identity

# Simulate a policy
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::<account>:role/<role> \
  --action-names s3:GetObject \
  --resource-arns arn:aws:s3:::<bucket>/<key>

# List attached policies
aws iam list-attached-role-policies --role-name <role>
```

## Related

- see_also → [[oncall-escalation-matrix]]: when to page Security Team vs self-resolve

## Sources

1. [AWS IAM Permission Error Troubleshooting SOP](examples/sample_data_en/kb/aws_iam_errors/sop.md:8-21) — error code table

## Changelog

- v1.0.0 (2026-05-06): initial; derived from doc_e5f6a7b8
