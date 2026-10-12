# SOLR-40 v3b causal audit

This is a **prior-witness-seeded directed replay**, not a Mallory automatic
discovery result. The replay injected one synthetic, final-visible
`KeeperException.ConnectionLossException` at the existing
`AliasesManager.process:2312` `getData(/aliases.json)` door on physical
`node3`, ordinal 1. It does not model a complete network disconnect and
reconnect. It does not establish a distinct new upstream Solr issue.

The separate v3b run used the unchanged Solr 8.11.4
`TimeRoutedAliasUpdateProcessorTest#test`. Its healthy control r0000 passed.
The first fault trial r0001 reproduced the exact target exception, so the
runner stopped after one of its twelve allowed fault trials. `site_catalog`
validated the pinned target class and `@133:callthrow:7` in both trials.

| Order | Raw event | Evidence |
| --- | --- | --- |
| 1 | `FAULT_APPLIED` `SOLR-40-r0001:4972` | `node3`, ordinal 1, `ConnectionLossException`, watcher task on `zkCallback-65-thread-1` |
| 2 | `STATE_READ` `SOLR-40-r0001:5094` | target request read `AliasesManager#aliases` from manager object `o100`, value object `o165`; the faulted watcher was also on manager `o100` |
| 3 | `TARGET_CHECK` `SOLR-40-r0001:5096` | `node3`, `FALLTHROUGH` into the empty-properties branch at `getAliasProps:132` |
| 4 | `TARGET_THROW` `SOLR-40-r0001:5097` | same target occurrence, `@133:callthrow:7`, `org.apache.solr.common.SolrException`, 173.45 ms after fault |

No `AliasesManager#aliases` `STATE_WRITE` on `node3` manager `o100`
occurred between the fault and target throw. The Solr log shows the watcher
catching the connection loss at line 2194, `CREATEALIAS` returning status 0
at line 2222, and the update returning HTTP 500 at line 2337. Its cause stack
reaches `RoutedAliasUpdateProcessor.getAliasProps:133` at line 2277. The
underlying code calls `RoutedAlias.newAliasMustExistException`, which itself
throws the recorded `SolrException`. Mallory feedback now reports
`target_reached=true`, `target_threw=true`,
`target_exception_candidate=true`, and `fault_identity_valid=true`.

The prior v2 ten-run raw traces remain unchanged. Independent source and
JUnit stack audit found the same target exception in two of those ten
injected runs, although v2 feedback missed both because its caller `ATHROW`
probe was unreachable. The v3b result validates the replacement call-throw
probe on a live Solr target path.

## Raw evidence hashes

All paths below are under
`data/mallory/solr40_callee_probe_v3b_node0/SOLR-40/`.

| Artifact | SHA-256 |
| --- | --- |
| `probe-validation-audit.json` | `50deb8a2a379a8620215a625663beba65c4c5f3a0a6a63f2c6366e38ad96da10` |
| `trials/r0001/events.jsonl.gz` | `112f630a697792458b2bc6d68fb01c42f3cb6e7e47e95693ae5ef24d29dea8f6` |
| `trials/r0001/junit.log` | `c549d0b625e498567e0231ce09709f35def39e7d5ebd23650b759f80612c8b48` |
