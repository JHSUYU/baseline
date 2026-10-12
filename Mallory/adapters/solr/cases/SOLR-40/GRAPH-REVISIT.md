# SOLR-40 graph-guided revisit

The original Solr 8.11.4 four-node embedded-cluster
`TimeRoutedAliasUpdateProcessorTest#test` is the workload in every row. The
healthy run must pass and reach the selected `getAliasProps` check. Each fault
trial injects one `KeeperException.ConnectionLossException` at an observed
`AliasesManager.process` read. The scheduler collects target, graph, actor,
coverage, and fault feedback after each run. These are independent campaigns
with separate output directories and bounded budgets; no candidate result is
counted from the earlier directed replay.

| Campaign | Host | Fault trials | Effective | Post-fault target reached | Exact target throws | End | Seconds |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: |
| graph-auto-v4 | node0 | 7 | 7 | 6 | 0 | queue exhausted | 221 |
| graph-auto-v5 | node0 | 37 | 37 | 33 | 0 | queue exhausted | 1076 |
| graph-auto-v6 | node1 | 13 | 13 | 11 | 0 | queue exhausted | 396 |
| graph-auto-v7 | node2 | 9 | 9 | 4 | 0 | queue exhausted | 286 |
| graph-auto-v8 | node0 | 21 | 21 | 15 | 0 | queue exhausted | 633 |
| **graph-auto-v9** | **node1** | **30** | **30** | **26** | **3** | trial budget | **838** |
| graph-auto-v10 | node2 | 20 | 20 | 15 | 0 | queue exhausted | 603 |

Across these seven campaigns, 137/137 fault trials applied their selected
fault effectively, 110 reached the target after injection, and three trials
threw the exact target exception. All three hits are in v9: r0003 and its
immediate automatic candidate replay r0004 used node2 ordinal 1; r0024 used
node3 ordinal 1 after a bounded actor-miss replay. The campaign recorded one
reproduced candidate pair (r0003/r0004). These are multiple observations of
**one** SOLR-40 failure path, not three distinct bugs.

The first automatic hit was selected as `dynamic_closure`, so it directly
shows the graph-guided queue can expose the target. The node3 hit used
`actor_miss_replay`, showing that target routing can hide a fault in the first
trial and that bounded reruns can help. The branch-replay setting was enabled
in v8-v10, but neither v9 hit originated from `target_branch_replay`; no hit
is attributed to that option. The non-hit campaigns are negative evidence
within their stated budgets, not a proof that the fault cannot trigger.

The exact event sequence, source interpretation, and evidence hashes are in
`graph-auto-v9/AUTO-CANDIDATE-AUDIT.md`. Source and existing-issue comparison
are in `targeted-replay-v3/UPSTREAM-REVIEW.md`. This is a reproducible
fault-induced target exception in Solr 8.11.4; whether it is a previously
unreported upstream defect and how it behaves under a real ZooKeeper network
failure remain open.
