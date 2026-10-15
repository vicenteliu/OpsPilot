# d7-v1 on the label set's Incidents: the engines compared

39 Incidents is not a benchmark: synthetic, English, labelled by one person, and the threshold is set on the same rows it is reported on; there is no held-out split at this size. Each engine answered every Incident 3 times; the figures pool the runs.

Labelled: single_user 32, multiple_users 7, site_wide 0. Always answering single_user would be 82.1% right.

| Engine | Calls ok/failed | Accuracy | Within one level | Brier on the answer | Cost/call | p50 | p95 |
|---|---|---|---|---|---|---|---|
| typesafe:jev-1.13.0 | 117/0 | 91.5% | 100.0% | 0.054 | $0.000019 | 80 ms | 158 ms |
| playbook:anthropic/claude-haiku-5-5 | 117/0 | 99.1% | 100.0% | 0.088 | $0.000059 | 691 ms | 1696 ms |

## What each engine answered, by label

| Engine | Labelled (answers) | single_user | multiple_users | site_wide |
|---|---|---|---|---|
| typesafe:jev-1.13.0 | single_user (96) | 90 | 6 | 0 |
| typesafe:jev-1.13.0 | multiple_users (21) | 1 | 17 | 3 |
| playbook:anthropic/claude-haiku-5-5 | single_user (96) | 95 | 1 | 0 |
| playbook:anthropic/claude-haiku-5-5 | multiple_users (21) | 0 | 21 | 0 |

## Threshold: the lowest probability at which the levels decided are at least 95.0% right

| Engine | Threshold | Decided without a person | Right among them |
|---|---|---|---|
| typesafe:jev-1.13.0 | 0.700 | 106/117 (90.6%) | 95.3% |
| playbook:anthropic/claude-haiku-5-5 | 0.450 | 117/117 (100.0%) | 99.1% |

The stage applies its threshold to the primary engine's probability; an answer from the fallback always goes to a person.
