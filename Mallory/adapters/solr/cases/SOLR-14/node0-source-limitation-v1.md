# SOLR-13 / SOLR-14 node0 static admission audit

Scope: read-only source, bytecode, package, and prior healthy evidence. No JVM,
fault, or checklist update was performed. This receipt does not grant runtime
admission.

## Strongest exact pretarget door: SOLR-14

The unchanged `SplitShardTest#doTest` (`SplitShardTest.java:76-92`) creates a
one-node `MiniSolrCloudCluster` and submits a valid split request. The source
checkout is Solr 8.11.4 commit
`e27f44e3d78dfcec230c97e0a1240e3751daeff9`; the JUnit source SHA-256 is
`decc7968002ca73c787318012f3356a72b681f85c3e2873d5f2326465320daad`.
`SplitShardCmd.java` SHA-256 is
`995355f882947b528cedf9b7b38032f334afec74b5226d217f3f7828f2fb34f3`.
Its compiled `SplitShardCmd.class` in `solr-core-8.11.4.jar` has SHA-256
`590ff068f83f4c7644891c19db9900911bf93a1a306de2f30c176568850ea93a`.

`SplitShardCmd.split` calls `SolrZkClient.exists` at source line 164. The
selected check is the `leaderZnodeStat == null` branch at line 165,
`@165:branch:5`, with the line-167 `SolrException` throw. The line-164 door is
`@164:door:2`, typed as `KeeperException.ConnectionLossException`. The
SHA-256-bound v30 healthy evidence is
`data/mallory/calibration_v30_lane1/SOLR-14/result.json`
(`946f08c9e52241080288913d64526f3287b8ff8366e26e017c334c34eb35a03a`)
and `trials/r0000/events.jsonl.gz`
(`03da19cd79bf456099e70a44358849d318bc369afffcea3005e961f15ff1e333`).
That JUnit passed 1/1, the loaded target class matched the expected hash, and
the exact check was reached three times on named physical `node1` with zero
target throws. The raw events pair door→check sequences `1683→1685`,
`9531→9533`, and `9984→9986`; each pair has the same node, epoch, thread,
task context, and `SplitShardCmd.split` occurrence. This proves local
healthy pretarget order for the selected door.

The typed fault does **not** retain this target check in the same invocation.
`split` declares `throws Exception` at line 106. Its nearby catch at lines
149-154 handles only `InterruptedException` from `getLeaderRetry`; no catch
surrounds `exists` at line 164. A `ConnectionLossException` at that call exits
`split` before line 165. A later separate split request is a new occurrence,
not retention of the selected check. Thus the direct line-164 door is suitable
for a healthy mapping check but should not be promoted as the fault door for a
target-retention campaign. A distinct upstream or background typed door would
need its own healthy causal proof and postfault retention pilot.

## Package and node0 gate

The committed `SOLR-14/successor-v2` package is pinned to **node2** and
`/users/ZhenyuLi/.mallory-worktrees/solr-lane3`. Its healthy and full
`run_campaign.py --preflight-only` checks both fail on node0 at the first
missing lane3 runtime source file,
`solr/core/src/test/org/apache/solr/schema/MockExchangeRateProvider.java`.
Node0 has the clean pinned inventory source and compiled Solr JAR, but that
does not authorize replacing the package's node2 paths or hashes. The node2
runner itself requires host `node2`, lane3 and shared-source locks, matching
dispatch GO receipts, 8 GiB available RAM, and at least 7,650,410,496 free
bytes. Node0 had about 6.97 billion free bytes at audit, below that floor.
There is no node0 SOLR-14 GO request or runnable package.

## SOLR-13 comparison

The unchanged `TimeRoutedAliasUpdateProcessorTest#testPreemptiveCreation`
healthy JUnit passed and hit `RoutedAlias.doSynchronous@348:branch:1` five
times on named node1/node4. Its exact line-2259 `SolrZkClient.setData`
`BadVersionException` door appeared 20 times on node1. However, the
SHA-bound `SOLR-13/source-admission-v1/healthy-audit-node2-lane3.json`
reports no nonempty event-time graph path from a selected Overseer write door
to any selected target check. The alias-write task context differs from the
request target context; temporal inclusion in the target region does not prove
a request/reply edge or one occurrence. SOLR-13 therefore does not satisfy the
requested same-actor/occurrence gate. Its node2 role package needs a fresh
healthy role receipt before any separate campaign consideration.

**Dispatch gate:** neither case is ready for a node0 full admission. If a
healthy-only Solr lane is available after the active ZK campaign, prefer a
case with a typed pretarget door that source can absorb while retaining the
target. SOLR-14's direct door can only serve as mapping calibration; SOLR-13
requires cross-actor causal linkage. Recheck node0 disk, locks, source pins,
and a new host-specific preflight before any later runtime request.
