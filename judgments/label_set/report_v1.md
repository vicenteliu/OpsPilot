# d2-v1 on the label set: the engines compared

80 rows is not a benchmark: synthetic, English, labelled by one person, and the threshold is set on the same rows it is reported on; there is no held-out split at this size. Each engine answered every row 3 times; accuracy and Brier pool the runs.

| Engine | Calls ok/failed | Accuracy | Across runs | Brier | Accuracy, low (17) | Brier, low | Cost/call | p50 | p95 |
|---|---|---|---|---|---|---|---|---|---|
| typesafe:jev-1.13.0 | 240/0 | 87.1% | 86.2%–87.5% | 0.102 | 51.0% | 0.373 | $0.000019 | 101 ms | 179 ms |
| playbook:anthropic/claude-haiku-4-5-20251001 | 240/0 | 88.8% | 88.8%–88.8% | 0.083 | 58.8% | 0.260 | $0.001031 | 1051 ms | 1284 ms |
| playbook:anthropic/claude-haiku-5-5 | 240/0 | 88.8% | 87.5%–90.0% | 0.077 | 58.8% | 0.233 | $0.000159 | 1048 ms | 2074 ms |

## Threshold: the lowest probability at which routed items are at least 95.0% right

| Engine | Threshold | Routed without a person | Right among routed |
|---|---|---|---|
| typesafe:jev-1.13.0 | 0.940 | 208/240 (86.7%) | 95.2% |
| playbook:anthropic/claude-haiku-4-5-20251001 | 0.750 | 207/240 (86.2%) | 95.7% |
| playbook:anthropic/claude-haiku-5-5 | 0.700 | 200/240 (83.3%) | 95.5% |

The stage applies its threshold to the primary engine's probability; an answer from the fallback always goes to a person.

## Self-consistency (SPEC §6)

- type 10/10 (95% CI 72.2%–100.0%)
- security 10/10 (95% CI 72.2%–100.0%)
