# SOLR-39 v6 sealed offline continuation

This package corrects the v5 postfault audit without changing the live v5
package, its raw evidence, the shared graph, or the target code. Run
`python3 reconcile.py --preflight-only` to verify the archived v5 evidence,
rerun the audit, and compare the result with the checked-in continuation
checkpoint. The command does not start Java or the cluster test.

The fault identity remains the exact `getData("/aliases.json", ...)` watcher
door, actor, epoch, ordinal, thread, occurrence, and run-local
`AliasesManager` object. The typed `ConnectionLossException` prevents that
watcher occurrence from calling `setIfNewer`. A later target check earns
target-oriented feedback only if a **prior** exact Java `Aliases` reference
was published on that same manager, read after the fault, returned through a
balanced getter, and reached `@246` through observed exact-reference and
program-return edges. The writer may be Solr's admin path
`applyModificationAndExportToZk`, which also calls `setIfNewer`; v5's
candidate enumerator incorrectly required a watcher door as the writer's
parent. A JUnit failure and process exit are reported as workload outcomes,
separate from an intact target-oriented path. A timeout, truncated trace,
bad resource/actor/manager identity, or unmatched fault earns no novelty.

An exact `@247` `TARGET_THROW` with `SolrException` is separately listed as
a source-review candidate when it belongs to a postfault target occurrence
on the bound actor with a read from the bound manager. A candidate alone is
not a confirmed bug. The sealed v5 traces contain no such throw.

| v5 trial | Strict v6 result | Reason |
| --- | --- | --- |
| r0001 | invalid | The bound node2 target path was lost; a failing JUnit is recorded separately. |
| r0002 | invalid | The bound node3 target path was lost. |
| r0003 | valid | On node2/epoch 0, manager `o10` published ref `81`, ZK version `15`, at seq 32094; fault applied at 32106; same manager read at 32892; balanced return reached `@246` at 32895. |

The cumulative v5 budget used 3 of 12 fault trials and 142.739 of 2400
seconds; the limit remains three faults per trial. The only strict-valid seed,
r0003, faults the last of the three qualified late watcher doors. The two
earlier seeds cannot create children, and the deduplicated continuation queue
is empty. `continuation-checkpoint.json` records all three seen plan hashes,
zero reruns, the remaining budget, and this terminal reason. `stage-request.json`
keeps `go=false` and `runtime_ready=false` because there is no qualified next
plan. The result is a completed bounded case-local campaign, with no new bug
confirmed.

`terminal-replay-receipt.json` records the deterministic sealed replay and
`canonical-import-proposal.json` maps its counts and evidence into a proposed
canonical result and checklist row. The proposal does not modify the table;
dispatch verifies and imports it separately.

The v5 tarball SHA and each tar member are checked against the sealed member
manifest. The local files consumed by the auditor are separately checked
against that manifest. Mutable trial scratch files are read only from the
sealed tarball for integrity checking and are never used for the audit.
