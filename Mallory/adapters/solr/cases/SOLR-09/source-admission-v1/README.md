# SOLR-09 source and JUnit admission

This is a **healthy-only** selector for the unchanged Solr 8.11.4 JUnit. It
stages no fault and makes no bug claim. The clean source checkout is pinned to
`e27f44e3d78dfcec230c97e0a1240e3751daeff9`; `manifest.json` binds the
source files, test, runner, agent, adapter, bytecode, config, and selected
sites by SHA-256. Run `python3 preflight.py` before dispatch. The script reads
files and does not launch a JVM.

## Selected path

`org.apache.solr.cloud.DeleteReplicaTest#deleteReplicaAndVerifyDirectoryCleanup`
is an existing `MiniSolrCloudCluster` test. Its `setUp` creates four nodes
(`DeleteReplicaTest.java:70-80`); the test creates a one-shard, two-replica
collection and deletes its live leader synchronously through
`CollectionAdminRequest.deleteReplica(...).process(...)` (`149-162`). It then
checks leader replacement and instance/data directory removal (`164-170`).
The test source SHA-256 is
`70e79d52bbc9e312cfb739d727b57ee99f66956068ab0a2a65df46efb13bd970`.

The exact selected check is
`DeleteReplicaCmd#deleteCore(...)@277:branch:7`. On the synchronous path,
`!callable.call()` raises the selected `SolrException` at line 278. The
compiled `DeleteReplicaCmd.class` SHA-256 is
`a76f7f732bd13437f37a44e4e0eaee13e053b0a6ae72b571bea1b3ec6b623c3b`.
The `parallel=true` path submits the callable and does not execute this guard.

The live-replica path sends a CoreAdmin `UNLOAD` through
`ShardRequestTracker.sendShardRequest` (`DeleteReplicaCmd.java:248-252`),
consumes the response in the callable (`254-257`), and waits for the core node
to disappear (`260`). If that wait returns false, it offers a `DELETECORE`
state update (`264`) and waits again (`265`). Two false waits make the callable
return false (`266`) and reach the selected throw. A thrown exception in the
callable instead reaches the catch/wrapper at `282-283`; it does not prove the
selected line-278 throw. `processResponses(..., abortOnError=false, ...)`
records an HTTP error without necessarily aborting the Boolean path.

The staged typed door is the exact call at
`OverseerCollectionMessageHandler.waitForCoreNodeGone:434` to
`ZkStateReader.waitForState(String,long,TimeUnit,Predicate)`. Its declared
`TimeoutException` is caught in `waitForCoreNodeGone` and mapped to false at
`443-445`. This is a coordination wait over watched cluster state, not a raw
ZooKeeper read. The same callsite serves the initial and fallback waits; a
fresh trace must distinguish them by occurrence, order, and door ordinal.
When watcher registration needs a fresh state, the underlying typed ZooKeeper
read is `ZkStateReader.fetchCollectionState:1641` calling
`SolrZkClient.getData`; `StateWatcher.refreshAndWatch:1390-1392` catches
`ConnectionLossException`. That lower-level read is conditional on watcher
state and is not assumed to occur in the target invocation. The fallback
`Overseer.offerStateUpdate:1025` writes to the state-update queue. These
operations are source candidates, not admitted target-closure doors yet.

## Archived evidence and fresh gate

The archived v10 healthy run passed one JUnit and hit the exact guard once on
`node1`; its named target backward closure had **zero** doors and **zero**
parent edges. Its trace and summary hashes are in `manifest.json`. It proves
test and target reachability only. The v19 adapter selected here binds the
Overseer command to the owning `CoreContainer`/`ZkController`, and the sites
add a `processMessage` parent region and the typed wait door. Their actual
runtime events remain unverified.

Dispatch may run `healthy.json` only after reserving a Solr lane. Admit the
result for further work only if the fresh unchanged JUnit passes, the exact
line-277 check fires on a registered server actor with a verified target class
and loader, and the selected target occurrence has an observed named
`processMessage` parent edge. The typed door must precede the check on that
same actor, epoch, thread, and `deleteCore` occurrence. Require its event-time
edge into the selected backward closure; if the graph builder cannot model
this synchronous nested call, label a same-occurrence ordered timeline
explicitly and leave graph admission open. An unknown actor, merely global
door count, child task without a completion edge, or a later door is a gap.
No fault campaign follows from a JUnit pass alone.

## Node2 lane3 staging

`healthy-node2-lane3.json` uses the same source and selected sites with the
v38 adapter and the pinned thread-ID-capable agent. It enables strict
event-time paths and rejects coarse roots. The separate
`run_node2_lane3_healthy.sh` acquires both the node2 lane3 lock and a lock for
this source checkout, checks a 7.125 GiB disk reserve and 8 GiB available RAM,
verifies pinned inputs, and runs exactly one calibration trial at a new output
path. `preflight.py --node2` validates the node2 variant without a JVM. The
v19 `healthy.json` remains a source triage seed; use the node2 variant for
fresh runtime admission. Even if a local timeline is reported, an observed
graph edge and target closure are still required before any fault promotion.
