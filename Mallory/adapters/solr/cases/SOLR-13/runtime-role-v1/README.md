# SOLR-13 staged full campaign

The unchanged Solr 8.11.4 JUnit is
`TimeRoutedAliasUpdateProcessorTest#testPreemptiveCreation`. The prior node2
healthy run passed 1/1 test and reached the exact
`RoutedAlias.doSynchronous@348:branch:1` check five times on named node1/node4
actors. It observed 20 exact
`ZkStateReader$AliasesManager.applyModificationAndExportToZk@2259` doors on
named node1. The door calls `SolrZkClient.setData`; a typed
`KeeperException.BadVersionException` is caught, followed by alias refresh
and a retry. The v10 run failed during ConfigSet creation before the target;
the established JUnit uses Solr's source-defined ConfigSet test flag and
`MALLORY_SOLR_AWAITSFIX=1`. These flags remain in the full config.

The prior healthy trace did not prove a unique request/reply edge from the
Overseer alias write to a selected target check. That graph fact is retained
as an outcome. The case-local agent binds a `maintain-routed-alias-write`
role only when the exact typed door executes inside both
`AliasesManager.applyModificationAndExportToZk` and the active
`MaintainRoutedAliasCmd.call` parent region on a named node/epoch. It emits
the physical actor and both region occurrences on `DOOR_OBSERVED`,
`FAULT_MATCHED`, and `FAULT_APPLIED`. Unnamed or unrelated alias writes do
not receive role ordinals. The campaign converts only such observed exact
doors to `{site, role, role_ordinal}` plans; all other doors are excluded.
It does not infer a cross-actor causal edge from timing or alias-name equality.

`config-full-node2.json` stages a fresh healthy seed followed by up to 80
fault trials, 3600 cumulative trial seconds, and at most three faults per
trial. The new role receipt must appear in that fresh healthy run before
faults can be queued. Graph and postfault path evidence are campaign
outcomes under the current terminal-full completion rule. A passing healthy
test and source-level retry do not claim a new bug.

`run_full_node2.sh` requires a separate case-local
`admission-full-node2.json` dispatch GO receipt matching node2, config SHA,
runner SHA, and intended output. It also holds node2 lane3 and shared Solr
source locks and checks disk and RAM floors. The current
`admission-request.json` has `go=false`; no node2 JVM has been launched for
this package. `run_campaign.py --preflight-only` checks source revision,
source and bytecode hashes, runtime artifacts, and config without a JVM.

Node0 verification: case-local agent `mvn -q test package` passed, including
two registry tests and one probe integration test; Python campaign mutation
test, shell syntax, and no-JVM preflight passed. Release agent SHA-256:
`bee26189cf56dc3030ab0f7d5997c352f5998c9f65bf3b8da2de1f99bec3f89e`.
