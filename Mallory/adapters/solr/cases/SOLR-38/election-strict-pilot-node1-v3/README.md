# SOLR-38 v3: source-backed strict state path and bounded fault pilot

This stage runs the unchanged `CloudHttp2SolrClientTest#testAliasHandling` mini cluster JUnit on node1. It uses the exact adapter JAR from the sealed v2 healthy run, the same pinned agent, and an isolated graph extension. No Solr test or shared Mallory core file is edited.

## Graph edge

The case-local `SourceBackedSolr38Graph` consumes the complete trace and the pinned Solr/adapter source checked by `election-unique-writer-audit-v1/audit.py`. For each target invocation, it accepts only a typed `getChildren` door at line 396, a same-thread `CloudDescriptor.setLeader(true)` native write, a getter return of `true` on the **same descriptor object**, and the target branch after that getter. The descriptor has exactly its constructor initialization and one setter write in the complete trace; the setter must be the last native writer before the getter with no intervening write. The setter is the only direct field writer in pinned `CloudDescriptor.java`; the diagnostic adapter duplicates the actual setter argument and getter return from the JVM stack. The target source assigns `localIsLeader` only from this getter.

The overlay adds two observed graph edges for an accepted witness: the typed door's return to its enclosing election invocation (`program_order`), and the exact descriptor's setter value event to its getter value event (`state`). The latter is **source-backed last-writer evidence**, not a generic promotion of sampled versions. The stock graph and its sampled candidate state edges stay unchanged. The source-backed edge is admitted only for this pinned Solr version, event shape, object, node, epoch, thread, election interval, and target invocation. If a fault changes that path, the extension withholds the edge.

Offline replay of sealed v2 evidence yields 12 strict door-to-target paths, two in-closure typed doors on node1/node3, and four distinct source-backed state event pairs. Six negative controls remove the path for a wrong descriptor, competing setter, wrong thread, wrong exception, or absent target.

## Bounded run gate

The v3 campaign has a **fresh healthy r0000**. Before any injection, `run_campaign.py` independently verifies a strict path containing a source-backed state edge, passing JUnit, runtime class attestation, exact target reachability, and a typed in-closure door. If this fails, it records `healthy_strict_path_missing` and clears the queue. The configured fault site is only the line 396 ZooKeeper `getChildren` `ConnectionLossException`; outside-closure exploration is disabled. The budget is at most **4 fault trials, 1 exception per trial, 1,800 seconds total**, with a 480-second per-trial timeout. A fault result is accepted as target-retained only when the exact target check occurs **after** a matched and applied fault. Target loss is recorded, not counted as a bug.

The campaign is restartable from its checkpoint, but a checkpoint with a completed healthy trial and no strict proof is rejected. The node1 operator must use the case-local dispatch GO receipt and lane/source locks. The launch checks free disk, available memory, and other user JVMs before starting. The direct JUnit runner checks the exact agent and adapter environment inherited from the controller.

Run static checks on node0 or node1 without launching a JVM:

```sh
python3 Mallory/adapters/solr/cases/SOLR-38/election-strict-pilot-node1-v3/test_offline.py
python3 Mallory/adapters/solr/cases/SOLR-38/election-strict-pilot-node1-v3/run_campaign.py --preflight-only
```

After dispatch stages `admission-strict-pilot-node1.json`, the node1 operator launches `run_campaign.py --admission-receipt <that exact path>` in the assigned tmux lane. `run_audit.py` recomputes a terminal campaign using the same isolated graph extension. A target exception is a candidate until the trace, exact source, and replay are reviewed; this package makes no bug claim.
