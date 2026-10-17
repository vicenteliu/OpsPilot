# d2-v1 on the label set: the engines compared

80 rows is not a benchmark: synthetic, Chinese, labelled by one person, and the threshold is set on the same rows it is reported on; there is no held-out split at this size. Each engine answered every row 3 times; accuracy and Brier pool the runs.

| Engine | Calls ok/failed | Accuracy | Across runs | Brier | Accuracy, low (8) | Brier, low | Cost/call | p50 | p95 |
|---|---|---|---|---|---|---|---|---|---|
| typesafe:jev-1.13.0 | 240/0 | 86.2% | 86.2%–86.2% | 0.111 | 50.0% | 0.434 | $0.000020 | 81 ms | 159 ms |
| playbook:anthropic/claude-haiku-5-5 | 240/0 | 90.4% | 88.8%–91.2% | 0.082 | 66.7% | 0.253 | $0.000162 | 1064 ms | 2455 ms |

## Threshold: the lowest probability at which routed items are at least 95.0% right

| Engine | Threshold | Routed without a person | Right among routed |
|---|---|---|---|
| typesafe:jev-1.13.0 | 0.990 | 192/240 (80.0%) | 95.3% |
| playbook:anthropic/claude-haiku-5-5 | 0.780 | 176/240 (73.3%) | 98.9% |

The stage applies its threshold to the primary engine's probability; an answer from the fallback always goes to a person.

## The English cut on this set

Each engine's cut in `d2.yaml` was measured on the English set. On this one it routes:

| Engine | English cut | Routed without a person | Right among routed |
|---|---|---|---|
| typesafe:jev-1.13.0 | 0.940 | 201/240 (83.8%) | 94.0% |
| playbook:anthropic/claude-haiku-5-5 | 0.700 | 200/240 (83.3%) | 92.5% |

## Self-consistency (SPEC §6)

no relabel file: the set has not been relabelled yet.
