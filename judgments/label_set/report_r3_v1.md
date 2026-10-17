# r3-v1 on the label set's requests with a catalog item: the engines compared

25 requests with a catalog item is not a benchmark: synthetic, English, labelled by one person, and the threshold is set on the same rows it is reported on; there is no held-out split at this size. Each engine answered every one 3 times; the figures pool the runs.

Labelled: yes 9, no 16. Always answering no would be 64.0% right.

| Engine | Calls ok/failed | Accuracy | Brier on the answer | Cost/call | p50 | p95 |
|---|---|---|---|---|---|---|
| typesafe:jev-1.13.0 | 75/0 | 90.7% | 0.093 | $0.000018 | 87 ms | 181 ms |
| playbook:anthropic/claude-haiku-5-5 | 75/0 | 81.3% | 0.118 | $0.000121 | 1427 ms | 2488 ms |

## What each engine answered, by label

| Engine | Labelled (answers) | yes | no |
|---|---|---|---|
| typesafe:jev-1.13.0 | yes (27) | 27 | 0 |
| typesafe:jev-1.13.0 | no (48) | 7 | 41 |
| playbook:anthropic/claude-haiku-5-5 | yes (27) | 16 | 11 |
| playbook:anthropic/claude-haiku-5-5 | no (48) | 3 | 45 |

## Threshold: the lowest probability at which the answers decided are at least 95.0% right

| Engine | Threshold | Decided without a person | Right among them |
|---|---|---|---|
| typesafe:jev-1.13.0 | 0.570 | 67/75 (89.3%) | 95.5% |
| playbook:anthropic/claude-haiku-5-5 | 0.720 | 51/75 (68.0%) | 96.1% |

The stage applies its threshold to the primary engine's probability; an answer from the fallback always goes to a person.

## Asks: the lowest P(no) at which the Work items asked about are at least 95.0% labelled no

Only a `no` that clears its cut acts: the run waits and the reporter is asked (decision 4, #229; r3, #294). A `yes`, or a `no` below the cut, goes on as before.

| Engine | Threshold | Asked | Right among them | Labelled no, asked | Labelled yes, asked |
|---|---|---|---|---|---|
| typesafe:jev-1.13.0 | 0.510 | 41/75 | 100.0% | 41/48 | 0/27 |
| playbook:anthropic/claude-haiku-5-5 | 0.700 | 43/75 | 95.3% | 41/48 | 2/27 |
