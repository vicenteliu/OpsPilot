# d1-v2 on the label set: the engines compared

80 rows is not a benchmark: synthetic, English, labelled by one person, and the threshold is set on the same rows it is reported on; there is no held-out split at this size. Each engine answered every row 3 times; the figures pool the runs. 41 of 80 rows are labelled `security: yes`.

| Engine | Calls ok/failed | Accuracy at 0.5 | Brier on P(yes) | Cost/call | p50 | p95 |
|---|---|---|---|---|---|---|
| typesafe:jev-1.13.0 | 240/0 | 62.5% | 0.338 | $0.000022 | 110 ms | 199 ms |
| playbook:anthropic/claude-haiku-5-5 | 240/0 | 65.4% | 0.284 | $0.000064 | 881 ms | 1535 ms |

## Threshold: the highest P(yes) at which every labelled security item reaches a person

| Engine | Threshold | Recall | Stopped | False alarms among the labelled no |
|---|---|---|---|---|
| typesafe:jev-1.13.0 | 0.020 | 123/123 (100.0%) | 240/240 (100.0%) | 117/117 (100.0%) |
| playbook:anthropic/claude-haiku-5-5 | 0.050 | 123/123 (100.0%) | 237/240 (98.8%) | 114/117 (97.4%) |

The stage stops a Work item at or above its primary engine's threshold on P(yes); an answer from the fallback always stops.
