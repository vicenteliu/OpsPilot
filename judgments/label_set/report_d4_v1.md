# d4-v1 on the label set's Incidents: the engines compared

39 Incidents is not a benchmark: synthetic, English, labelled by one person, and the threshold is set on the same rows it is reported on; there is no held-out split at this size. Each engine answered every one 3 times; the figures pool the runs.

Labelled: yes 35, no 4. Always answering yes would be 89.7% right.

| Engine | Calls ok/failed | Accuracy | Brier on the answer | Cost/call | p50 | p95 |
|---|---|---|---|---|---|---|
| typesafe:jev-1.13.0 | 117/0 | 90.6% | 0.108 | $0.000019 | 85 ms | 160 ms |
| playbook:anthropic/claude-haiku-5-5 | 117/0 | 88.0% | 0.076 | $0.000070 | 717 ms | 2456 ms |

## What each engine answered, by label

| Engine | Labelled (answers) | yes | no |
|---|---|---|---|
| typesafe:jev-1.13.0 | yes (105) | 94 | 11 |
| typesafe:jev-1.13.0 | no (12) | 0 | 12 |
| playbook:anthropic/claude-haiku-5-5 | yes (105) | 97 | 8 |
| playbook:anthropic/claude-haiku-5-5 | no (12) | 6 | 6 |

## Threshold: the lowest probability at which the answers decided are at least 95.0% right

| Engine | Threshold | Decided without a person | Right among them |
|---|---|---|---|
| typesafe:jev-1.13.0 | 0.550 | 107/117 (91.5%) | 95.3% |
| playbook:anthropic/claude-haiku-5-5 | 0.720 | 102/117 (87.2%) | 96.1% |

The stage applies its threshold to the primary engine's probability; an answer from the fallback always goes to a person.

## Asks: the lowest P(no) at which the Work items asked about are at least 95.0% labelled no

Only a `no` that clears its cut acts: the run waits and the reporter is asked (decision 4, #229; r3, #294). A `yes`, or a `no` below the cut, goes on as before.

| Engine | Threshold | Asked | Right among them | Labelled no, asked | Labelled yes, asked |
|---|---|---|---|---|---|
| typesafe:jev-1.13.0 | 0.640 | 12/117 | 100.0% | 12/12 | 0/105 |
| playbook:anthropic/claude-haiku-5-5 | 0.770 | 4/117 | 100.0% | 4/12 | 0/105 |
