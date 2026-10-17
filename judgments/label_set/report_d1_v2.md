# d1-v2 on the label set: the engines compared

80 rows is not a benchmark: synthetic, English, labelled by one person, and the threshold is set on the same rows it is reported on; there is no held-out split at this size. Each engine answered every row 3 times; the figures pool the runs. 14 of 80 rows are labelled `security: yes`.

| Engine | Calls ok/failed | Accuracy at 0.5 | Brier on P(yes) | Cost/call | p50 | p95 |
|---|---|---|---|---|---|---|
| typesafe:jev-1.13.0 | 240/0 | 96.2% | 0.035 | $0.000022 | 110 ms | 199 ms |
| playbook:anthropic/claude-haiku-5-5 | 240/0 | 96.7% | 0.026 | $0.000064 | 881 ms | 1535 ms |

## Threshold: the highest P(yes) at which every labelled security item reaches a person

| Engine | Threshold | Recall | Stopped | False alarms among the labelled no |
|---|---|---|---|---|
| typesafe:jev-1.13.0 | 0.100 | 42/42 (100.0%) | 55/240 (22.9%) | 13/198 (6.6%) |
| playbook:anthropic/claude-haiku-5-5 | 0.300 | 42/42 (100.0%) | 45/240 (18.8%) | 3/198 (1.5%) |

The stage stops a Work item at or above its primary engine's threshold on P(yes); an answer from the fallback always stops.
