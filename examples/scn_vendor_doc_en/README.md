# scn_vendor_doc_en — Vendor Document Generation

Demonstrates generating a vendor-facing operational document (SOP summary) from an English VPN troubleshooting KB.

## Quick Start

```bash
# 1. Load the KB fixture
opspilot kb load-fixture \
  --doc-meta examples/scn_vendor_doc_en/kb/doc-meta.json \
  --chunks   examples/scn_vendor_doc_en/kb/chunks.jsonl

# 2. Generate a vendor doc from the CLI
opspilot doc generate \
  --topic "VPN authentication failure troubleshooting" \
  --template sop_summary \
  --vendor "SecureNet Ltd" \
  --output /tmp/vendor_doc.json

# 3. Run the harness golden test
opspilot harness golden-vendor-doc
```

## Directory Layout

```
scn_vendor_doc_en/
├── kb/
│   ├── sop_vpn_en.md       English VPN SOP source document
│   ├── doc-meta.json        KB document metadata (doc_b1c2d3e4)
│   └── chunks.jsonl         Pre-chunked KB fixture (3 chunks)
├── harness/
│   ├── fixture.json         Test input (doc generation request)
│   └── golden.json          Expected output assertions
├── session/
│   └── inputs/
│       └── doc_request.json Example input JSON
└── README.md
```

## Harness Evaluators

| Evaluator | Weight | Checks |
|---|---|---|
| schema_check | 0.40 | Output validates against `vendor_doc_v1` |
| must_contain | 0.30 | Key terms appear in section content |
| must_not_contain | 0.10 | No internal jargon leaks |
| rag.citation_validity | 0.20 | All cited chunk_ids exist in KB |
