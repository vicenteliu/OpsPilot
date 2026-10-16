# r2-v1 on the label set's Work items, each as if filed as a request: the engines compared

80 Work items, each as if filed as a request is not a benchmark: synthetic, English, labelled by one person, and the threshold is set on the same rows it is reported on; there is no held-out split at this size. Each engine answered every one 3 times; the figures pool the runs.

Labelled: request 22, incident 47, change 11. Always answering incident would be 58.8% right.

| Engine | Calls ok/failed | Accuracy | Brier on the answer | Cost/call | p50 | p95 |
|---|---|---|---|---|---|---|
| typesafe:jev-1.13.0 | 240/0 | 88.8% | 0.089 | $0.000021 | 91 ms | 171 ms |
| playbook:anthropic/claude-haiku-5-5 | 240/0 | 87.9% | 0.094 | $0.000086 | 913 ms | 2330 ms |

## What each engine answered, by label

| Engine | Labelled (answers) | request | incident | change |
|---|---|---|---|---|
| typesafe:jev-1.13.0 | request (66) | 60 | 6 | 0 |
| typesafe:jev-1.13.0 | incident (141) | 3 | 135 | 3 |
| typesafe:jev-1.13.0 | change (33) | 15 | 0 | 18 |
| playbook:anthropic/claude-haiku-5-5 | request (66) | 60 | 3 | 3 |
| playbook:anthropic/claude-haiku-5-5 | incident (141) | 11 | 127 | 3 |
| playbook:anthropic/claude-haiku-5-5 | change (33) | 9 | 0 | 24 |

## Threshold: the lowest probability at which the answers decided are at least 95.0% right

| Engine | Threshold | Decided without a person | Right among them |
|---|---|---|---|
| typesafe:jev-1.13.0 | 0.890 | 189/240 (78.8%) | 96.8% |
| playbook:anthropic/claude-haiku-5-5 | 0.820 | 159/240 (66.2%) | 95.6% |

The stage applies its threshold to the primary engine's probability; an answer from the fallback always goes to a person.

## Named: the lowest probability at which the answers other than `request` are at least 95.0% right

`request`, and an answer below the cut, take the same way, so only another answer acts; this is its cut (#231, #293).

| Engine | Threshold | Named | Right among them | Labelled named, named rightly | Labelled request, named |
|---|---|---|---|---|---|
| typesafe:jev-1.13.0 | 0.710 | 154/240 | 95.5% | 147/174 | 4/66 |
| playbook:anthropic/claude-haiku-5-5 | 0.750 | 131/240 | 96.2% | 126/174 | 2/66 |
