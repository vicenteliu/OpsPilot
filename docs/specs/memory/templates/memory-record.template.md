---
# Mid-term memory record template
# fields must conform to schemas/memory-record.schema.json
# kept equivalent to the SQLite mid-term table (same unique id)

id: "mem_a1b2c3d4"                       # mem_<sha8>; computed at runtime
type: "feedback"                         # user | feedback | project | reference
scope: "opspilot:project"                # namespace
title: "RCAs list causal chains, not timestamp dumps"
tags: ["rca", "style"]

source:
  origin: "session"
  session_id: "sess_01J0Z9ZQXK7M6P3F0XK5K7C5K0"
  trace_seq: 42
  document_id: null
  url: null

created_at: "2026-05-01T11:00:00Z"
updated_at: "2026-05-01T11:00:00Z"
valid_until: null
confidence: "high"

redacted: true
redaction_rules_version: "1.0.0"

labels:
  team: "service-desk"
extensions: {}
---

When writing an RCA, do not enumerate timestamps; list the causal chain (cause → effect).

**Why:** The user gave explicit feedback in sess_01J0...: piling up timestamps makes
management miss the point; what they want to see is "what caused what" — timestamps
in an appendix are enough.

**How to apply:**
- In `playbooks/rca_*`, default the output to "a 3-part causal chain + an appendix timeline"
- The evaluator (harness) scores on "whether the output contains a 'cause→effect' or because/therefore structure"
- Exception: compliance-investigation tickets still keep itemized timestamps (a governance requirement)
