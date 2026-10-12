# d1-v1 on the label set: the engines compared

80 rows is not a benchmark: synthetic, English, labelled by one person, and the threshold is set on the same rows it is reported on; there is no held-out split at this size. Each engine answered every row 3 times; the figures pool the runs. 40 of 80 rows are labelled `security: yes`. Those labels were reviewed after labelling where they and the drafter split: 1 of 29 reviewed labels changed, and the review was not blind.

| Engine | Calls ok/failed | Accuracy at 0.5 | Brier on P(yes) | Cost/call | p50 | p95 |
|---|---|---|---|---|---|---|
| typesafe:jev-1.13.0 | 240/0 | 62.5% | 0.304 | $0.000019 | 98 ms | 168 ms |
| playbook:anthropic/claude-haiku-5-5 | 240/0 | 72.5% | 0.207 | $0.000065 | 826 ms | 1567 ms |

## Threshold: the highest P(yes) at which every labelled security item reaches a person

| Engine | Threshold | Recall | Stopped | False alarms among the labelled no |
|---|---|---|---|---|
| typesafe:jev-1.13.0 | 0.020 | 120/120 (100.0%) | 240/240 (100.0%) | 120/120 (100.0%) |
| playbook:anthropic/claude-haiku-5-5 | 0.080 | 120/120 (100.0%) | 227/240 (94.6%) | 107/120 (89.2%) |

The stage stops a Work item at or above its primary engine's threshold on P(yes); an answer from the fallback always stops.

## Self-consistency (SPEC §6)

- security 10/10 (95% CI 72.2%–100.0%)
