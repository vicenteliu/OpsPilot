# scn_request_fulfillment_zh

Service Request scenario fixture (Work item model). A new-hire VPN access request is processed into a `request_fulfillment_v1` artifact: `requested_item`, `approval_needed`, and tiered fulfillment `tasks[]`, with a KB citation.

- `session/inputs/ticket.json` — the service request input
- `session/artifacts/art_21ced918d3d0b388.json` — sample artifact (+ `.meta.yaml` sidecar)
- `harness/golden.json` — expected-shape golden
