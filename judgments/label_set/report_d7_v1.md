# d7-v1 on the label set's Incidents: the engines compared

51 Incidents is not a benchmark: synthetic, English, labelled by one person, and the threshold is set on the same rows it is reported on; there is no held-out split at this size. Each engine answered every one 3 times; the figures pool the runs.

Labelled: single_user 32, multiple_users 7, site_wide 12. Always answering single_user would be 62.7% right.

| Engine | Calls ok/failed | Accuracy | Within one level | Brier on the answer | Cost/call | p50 | p95 |
|---|---|---|---|---|---|---|---|
| typesafe:jev-1.13.0 | 153/0 | 93.5% | 100.0% | 0.042 | $0.000019 | 82 ms | 161 ms |
| playbook:anthropic/claude-haiku-5-5 | 153/0 | 99.3% | 100.0% | 0.072 | $0.000056 | 686 ms | 1594 ms |

## What each engine answered, by label

| Engine | Labelled (answers) | single_user | multiple_users | site_wide |
|---|---|---|---|---|
| typesafe:jev-1.13.0 | single_user (96) | 90 | 6 | 0 |
| typesafe:jev-1.13.0 | multiple_users (21) | 1 | 17 | 3 |
| typesafe:jev-1.13.0 | site_wide (36) | 0 | 0 | 36 |
| playbook:anthropic/claude-haiku-5-5 | single_user (96) | 95 | 1 | 0 |
| playbook:anthropic/claude-haiku-5-5 | multiple_users (21) | 0 | 21 | 0 |
| playbook:anthropic/claude-haiku-5-5 | site_wide (36) | 0 | 0 | 36 |

## Threshold: the lowest probability at which the answers decided are at least 95.0% right

| Engine | Threshold | Decided without a person | Right among them |
|---|---|---|---|
| typesafe:jev-1.13.0 | 0.660 | 147/153 (96.1%) | 95.2% |
| playbook:anthropic/claude-haiku-5-5 | 0.450 | 153/153 (100.0%) | 99.3% |

The stage applies its threshold to the primary engine's probability; an answer from the fallback always goes to a person.
