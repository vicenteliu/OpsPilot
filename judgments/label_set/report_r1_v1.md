# r1-v1 on the label set's service requests: the engines compared

41 service requests is not a benchmark: synthetic, English, labelled by one person, and the threshold is set on the same rows it is reported on; there is no held-out split at this size. Each engine answered every one 3 times; the figures pool the runs.

Labelled: vpn_access 3, new_account 1, mfa_reset 0, password_reset 0, group_membership 0, shared_mailbox 0, saas_access 8, software_install 0, new_hardware 1, loaner 2, hardware_return 1, reimage 3, certificate 5, recovery_key 0, admin_rights 0, guest_wifi 1, none 16. Always answering none would be 39.0% right.

| Engine | Calls ok/failed | Accuracy | Brier on the answer | Cost/call | p50 | p95 |
|---|---|---|---|---|---|---|
| typesafe:jev-1.13.0 | 123/0 | 85.4% | 0.113 | $0.000037 | 82 ms | 169 ms |
| playbook:anthropic/claude-haiku-5-5 | 123/0 | 82.9% | 0.113 | $0.000141 | 1099 ms | 2432 ms |

## What each engine answered, by label

| Engine | Labelled (answers) | Right | Said none | Another |
|---|---|---|---|---|
| typesafe:jev-1.13.0 | vpn_access (9) | 9 | 0 | 0 |
| typesafe:jev-1.13.0 | new_account (3) | 3 | 0 | 0 |
| typesafe:jev-1.13.0 | saas_access (24) | 24 | 0 | 0 |
| typesafe:jev-1.13.0 | new_hardware (3) | 3 | 0 | 0 |
| typesafe:jev-1.13.0 | loaner (6) | 6 | 0 | 0 |
| typesafe:jev-1.13.0 | hardware_return (3) | 3 | 0 | 0 |
| typesafe:jev-1.13.0 | reimage (9) | 9 | 0 | 0 |
| typesafe:jev-1.13.0 | certificate (15) | 15 | 0 | 0 |
| typesafe:jev-1.13.0 | guest_wifi (3) | 3 | 0 | 0 |
| typesafe:jev-1.13.0 | none (48) | 30 | – | 18 |
| playbook:anthropic/claude-haiku-5-5 | vpn_access (9) | 9 | 0 | 0 |
| playbook:anthropic/claude-haiku-5-5 | new_account (3) | 3 | 0 | 0 |
| playbook:anthropic/claude-haiku-5-5 | saas_access (24) | 18 | 3 | 3 |
| playbook:anthropic/claude-haiku-5-5 | new_hardware (3) | 2 | 0 | 1 |
| playbook:anthropic/claude-haiku-5-5 | loaner (6) | 6 | 0 | 0 |
| playbook:anthropic/claude-haiku-5-5 | hardware_return (3) | 3 | 0 | 0 |
| playbook:anthropic/claude-haiku-5-5 | reimage (9) | 7 | 0 | 2 |
| playbook:anthropic/claude-haiku-5-5 | certificate (15) | 15 | 0 | 0 |
| playbook:anthropic/claude-haiku-5-5 | guest_wifi (3) | 3 | 0 | 0 |
| playbook:anthropic/claude-haiku-5-5 | none (48) | 36 | – | 12 |

## Threshold: the lowest probability at which the answers decided are at least 95.0% right

| Engine | Threshold | Decided without a person | Right among them |
|---|---|---|---|
| typesafe:jev-1.13.0 | 0.950 | 74/123 (60.2%) | 95.9% |
| playbook:anthropic/claude-haiku-5-5 | 0.700 | 75/123 (61.0%) | 98.7% |

The stage applies its threshold to the primary engine's probability; an answer from the fallback always goes to a person.

## Named: the lowest probability at which the answers other than `none` are at least 95.0% right

`none`, and an answer below the cut, take the same way (a person checks), so only a named answer acts; this is its cut (#231).

| Engine | Threshold | Named | Right among them | Labelled named, named rightly | Labelled none, named |
|---|---|---|---|---|---|
| typesafe:jev-1.13.0 | 0.960 | 60/123 | 95.0% | 57/75 | 3/48 |
| playbook:anthropic/claude-haiku-5-5 | 0.700 | 48/123 | 97.9% | 47/75 | 1/48 |
