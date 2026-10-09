# SOLR-14/16 original-test reachability remap

Solr 8.11.4 source revision `e27f44e3d78dfcec230c97e0a1240e3751daeff9`.
This remap does not repeat the 163 previously recorded shared fault trials.

## Exact source conditions

| Check | Original source | State needed to take selected branch |
| --- | --- | --- |
| SOLR-14 | `SplitShardCmd.split`, lines 163–169 | `getLeaderRetry` has selected a parent leader, but `/live_nodes/<that node>` is absent at the **first** `exists` call; line 167 throws. |
| SOLR-16 | `SplitShardCmd.split`, lines 521–543 | First `exists` returns a non-null `Stat`; second `exists` returns a non-null `Stat` for the **same parent node** with a different `ephemeralOwner`; line 543 throws. A null second `Stat` takes SOLR-15's distinct line 538 throw. |

The line 524 outer guard is insufficient evidence that the SOLR-16 line 539 final guard executed. The parent node must actually stop before SOLR-14's first read or acquire a new ZooKeeper session between SOLR-16's two reads. An injected `ConnectionLossException` alone does not establish either state transition.

## Original cluster JUnit audit

The source search `rg -l 'splitShard\(' solr/core/src/test --glob '*.java'` found 12 split-using test classes. The relevant original methods and their ordering are:

| Original test | Cluster operation and target evidence | Window assessment |
| --- | --- | --- |
| `SplitShardTest#doTest` | Previously passed twice under independent ASM/JaCoCo; shard1 line 165 and line 524 guards executed. | One Jetty; no parent stop/restart. Its 80 entry-level and 80 retry-internal fault trials are already in the historical ledger. |
| `ShardSplitTest#testSplitWithChaosMonkey` | Previously passed three healthy runs; the two-fault replay reached SOLR-15's line 538 protective abort. | Its watcher stops the parent leader only after a child has over one replica (test lines 449–460), after SOLR-14's first read; it restarts parent only after split returns (lines 491–506), after SOLR-16's second read. |
| `ShardSplitTest#testSplitStaticIndexReplication` | Previously passed a multi-node healthy run; line 165 and line 524 guards executed. | Its Jetty restart is after the split completes (test lines 161–199). |
| `ShardSplitTest#testSplitAfterFailedSplit` | **New healthy smoke:** unchanged original JUnit passed `ran=1, ignored=0, failures=0` in 35.575 s; two exact SOLR-14 line 165 guards and one line 524 outer guard, zero final line 539 guards and zero selected throws. Direct line 164 `exists` ran twice, line 523 `exists` once; all refer to `collection1/shard1/PARENT_LEADER`. [Machine audit](remap-audit.json), [run metadata](run.json). | Original `TestInjection.splitFailureBeforeReplicaCreation` aborts the first split, then the test retries. It does not stop/restart the parent between the selected reads (test lines 287–332). This changes split state but not the required leader liveness/session state. |
| `ChaosMonkeyShardSplitTest#test` | Contains a leader stop/restart before `splitShard` (test lines 113–141). | The entire class has `@Ignore("SOLR-4944")` at line 54, so exact original JUnit selection is skipped. Even if run, its leader restart precedes split rather than occurring between its reads. |
| `CollectionsAPISolrJTest#testSplitShard`, `MultiThreadedOCPTest` split methods, `SplitByPrefixTest` split methods | Issue synchronous or asynchronous split requests. | Their original test method bodies do not stop or restart the selected parent leader during a split. Their additional requests do not establish the state transition for either target branch. |

The new healthy run used the existing case-local retry-internal ASM probe and production JaCoCo with the original compiled test source; its runtime classpath contains no GraphChecker. The raw trace remains on node2 at `SOLR-14/independent/supplemental/shardsplit/remap-failed-split-healthy-01/events.jsonl` (SHA-256 in `remap-audit.json`). The compact audit is mirrored here. No new fault was injected, and no previous fault trial was rerun.

**Disposition:** Both checks use the checklist's terminal `no_usable_cluster_test` status, scoped to the original embedded-cluster JUnits audited here and the current exception-only fault model. The more precise outcome is a **target-relevant workload gap**: SOLR-14's first guard executes, but no identified original test supplies early parent loss; SOLR-16's final changed-owner guard never executes, because no identified original test renews the same parent's session between reads. The prior 163 shared fault trials and separate multi-node evidence remain recorded. This is neither source exclusion nor a high-quality negative result, and it does not establish absence of a bug. A future campaign needs an original test or an authorized node crash/reboot fault that actually creates the missing transition. `bug_mark=none` for both.
