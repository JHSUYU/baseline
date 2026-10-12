# SOLR-09 Mallory revisit

The workload in every row is the unchanged Solr 8.11.4 four-node embedded
cluster test `DeleteReplicaTest#deleteReplicaAndVerifyDirectoryCleanup`.
The selected check is `DeleteReplicaCmd.deleteCore`'s `if (!callable.call())`
at line 277, which throws `Could not remove replica` at line 278 when both
30-second waits report that the replica remains.

These five experiments are **prior-witness-seeded directed timing diagnostics**.
They do not demonstrate automatic graph-guided discovery. Each starts with an
`IOException` at the CoreAdmin `UNLOAD` request, followed by a
`ConnectionLossException` at the same node's state-watch `getChildren`.
The variants change which subsequent collection-state `getData` call receives
another `ConnectionLossException`. Variant v3 adds a fourth fault at the next
state read. Each fault trial starts a fresh test cluster. All output directories
contain their pinned configuration, per-trial fault receipts, trace, JUnit log,
result, and cumulative summary.

| Variant | Host | Final state-read fault | Trials | Full injection | Post-fault target reached | Target throws | Trial seconds |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| v1 | node0 | watcher read, relative hit 2 | 8 | 0 | 0 | 0 | 370.404 |
| v2 | node0 | any state read, relative hit 2 | 20 | 10 | 10 | 0 | 923.617 |
| v3 | node0 | as v2, then another state read | 8 | 5 | 5 | 0 | 370.382 |
| v4 | node0 | any state read, relative hit 1 | 12 | 6 | 0 | 0 | 552.750 |
| v5 | node1 | any state read, relative hit 3 | 12 | 7 | 7 | 0 | 550.677 |

Across the five variants, 60 fault trials were completed, 28 applied the full
sequence effectively, 22 still reached the selected check after the final
fault, and none threw its selected exception. In v4, every effective sequence
lost the target; its six other trials did not match the full sequence. V5's
seven effective sequences retained the target but took its normal outcome.
The node1 v5 output was copied to the local `data/mallory` tree after the
campaign ended; the remote and local `summary.json` files have identical
SHA-256 `eeef64b7301f76c1664792927e1084bad4db560f5629e854abbe2702434ca1c2`.

The earlier CrashFuzz actor-aware replay remains separate positive evidence
for SOLR-09. Its source and fault review are in
`crashfuzz/cases/SOLR-09/actor-v2/CANDIDATE-059.md`. The Mallory results here
show that these particular role-relative timing choices have not reproduced
that witness in the stated budget. They do not negate the previous witness or
establish whether its failure is distinct from an existing upstream issue.
