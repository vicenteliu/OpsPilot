# d1-v2 on the label set: the engines compared

80 rows is not a benchmark: synthetic, Chinese, labelled by one person, and the threshold is set on the same rows it is reported on; there is no held-out split at this size. Each engine answered every row 3 times; the figures pool the runs. 12 of 80 rows are labelled `security: yes`.

| Engine | Calls ok/failed | Accuracy at 0.5 | Brier on P(yes) | Cost/call | p50 | p95 |
|---|---|---|---|---|---|---|
| typesafe:jev-1.13.0 | 240/0 | 98.8% | 0.010 | $0.000023 | 100 ms | 207 ms |
| playbook:anthropic/claude-haiku-5-5 | 240/0 | 98.8% | 0.016 | $0.000073 | 709 ms | 1538 ms |

## Threshold: the highest P(yes) at which every labelled security item reaches a person

| Engine | Threshold | Recall | Stopped | False alarms among the labelled no |
|---|---|---|---|---|
| typesafe:jev-1.13.0 | 0.470 | 36/36 (100.0%) | 36/240 (15.0%) | 0/204 (0.0%) |
| playbook:anthropic/claude-haiku-5-5 | 0.900 | 36/36 (100.0%) | 36/240 (15.0%) | 0/204 (0.0%) |

The stage stops a Work item at or above its primary engine's threshold on P(yes); an answer from the fallback always stops.

## The English cut on this set

Each engine's cut in `d1.yaml` was measured on the English set. On this one it stops:

| Engine | English cut | Recall | Stopped | False alarms among the labelled no |
|---|---|---|---|---|
| typesafe:jev-1.13.0 | 0.100 | 36/36 (100.0%) | 47/240 (19.6%) | 11/204 (5.4%) |
| playbook:anthropic/claude-haiku-5-5 | 0.300 | 36/36 (100.0%) | 42/240 (17.5%) | 6/204 (2.9%) |
