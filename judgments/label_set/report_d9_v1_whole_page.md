# d9-v1 on the label set: the engines compared

80 rows is not a benchmark: synthetic, English, labelled by one person, and the threshold is set on the same rows it is reported on; there is no held-out split at this size. Each engine answered every candidate page of every row 3 times, shown the whole page; the figures pool the runs. 44 of 80 rows have a known fix among their candidates.

| Engine | Calls ok/failed | Accuracy at 0.5, per page | Brier on P(yes) | Cost/call | p50 | p95 |
|---|---|---|---|---|---|---|
| typesafe:jev-1.13.0 | 918/0 | 80.1% | 0.152 | $0.000147 | 132 ms | 210 ms |
| playbook:anthropic/claude-haiku-5-5 | 918/0 | 80.1% | 0.169 | $0.000477 | 892 ms | 1570 ms |

## Threshold: the lowest P(yes) at which the fixes sent are at least 95.0% right

Per row and run, the candidate with the highest P(yes) is the fix the stage would send, and each count below is of rows and runs: a row counts once per run. A row and run with a page no call answered is left out.

| Engine | Threshold | Fixes sent | Right among sent | Rows with a fix, given a right page | Rows with none, sent a page |
|---|---|---|---|---|---|
| typesafe:jev-1.13.0 | none reaches 95.0% | – | – | – | – |
| playbook:anthropic/claude-haiku-5-5 | 0.120 | 25/240 (10.4%) | 24/25 (96.0%) | 24/132 (18.2%) | 1/108 (0.9%) |
