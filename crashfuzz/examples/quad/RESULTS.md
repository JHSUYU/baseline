# Four-system graph, fault, and code-coverage pilot

## What ran

The upgraded loop used a healthy workload to identify bytecode guards reached
on server JVMs, drew a fixed random sample, and ran each selected check with
its own fresh cluster and bounded crash/reboot trials. The controller injected
only at observed fault points during the workload. For the three newly added
systems, the strict trigger identity was `(node, process epoch, site,
call/async context, ordinal, phase)`; every injected action recorded its
planned and observed identities. The HDFS ten-check run preceded the epoch
check and required all of those dimensions except epoch. Each run built a
causal graph from call/return, observed state, asynchronous handoff, and
correlated message events. The queue used target-closure graph novelty,
basic-block coverage, and branch-outcome coverage when ranking the next
sequence. A mapped exact throw and the independent post-fault checker were
separate oracles. [Design and reproduction](README.md).

| System | Valid checks | Fault trials | Full matches | Full matches reaching target guard | New closure branch outcomes | Exact target throws | Confirmed new bugs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| HDFS 3.4.3, upgraded first-ten sample | 10 | 32 | 25 | 21 | 14 | 0 | 0 |
| HBase 2.6.6 | 10 | 29 | 11 | 10 | 4 | 0 | 0 |
| ZooKeeper 3.8.7 | 10 | 25 | 17 | 17 | 8 | 0 | 0 |
| Solr 8.11.4 | 10 | 23 | 19 | 18 | 28 | 0 | 0 |

“Full match” requires every planned action to have been injected at its
runtime trigger. A guard hit is evidence that the chosen check executed, not
that its failure predicate was true. These numbers are bounded observations;
they do not establish that the untested candidates or fault schedules are
safe. The [HDFS ten-check record](../hdfs_random10/COVERAGE10.md),
[HBase audit](../hbase_266/audit10.json),
[ZooKeeper audit](../zookeeper_387/audit10.json), and
[Solr audit](../solr_8114/audit10.json) preserve the per-check counts.

The earlier [HDFS 50-candidate campaign](../hdfs_random50/RESULTS.md) is a
separate CrashFuzz-style pilot. It selected 50 of the 532 HDFS candidates,
matched 89 of 104 planned trials, and found one replayable exact-location
throw. That throw was the expected `BlockReceiver` pipeline exception after a
DataNode crash; readback passed. That older run predates the upgraded
injection-window isolation and broad block/branch channel, so its 50 sites
are not represented as 50 upgraded measurements in the table.

## Candidate review

- **ZooKeeper draw 6:** An initial replayed `NoNodeException` at
  `FinalRequestProcessor.handleGetDataRequest` followed a leader crash. The
  first workload attempted `get` after its parent `create` had failed with
  `ConnectionLoss`. The corrected workload confirms parent creation before
  reading. Its exact-matched rerun reached the guard without an exact throw,
  and the checker passed. Draw 7's healthy seed already threw at its target;
  deterministic reserve draw 11 supplied the tenth valid check.
- **HBase workload/checker failures:** Four complete strict matches aborted
  the HBase shell workload with `PleaseHoldException: Master is initializing`.
  In all four, the checker reported that the client workload had not finished.
  None executed its mapped target throw. These runs show temporary operation
  unavailability during fault handling, not a demonstrated coordination-state
  violation. Their raw output remains under `../hbase_266/out_campaign/`.
- **HBase token check:** The user-specified
  `AuthenticationTokenSecretManager.retrievePassword` check at
  `allKeys.get(keyId)` maps to a direct bytecode guard, but the CRUD/snapshot
  workload never reached it. It is excluded from the ten HBase targets. A
  separate [token-RPC diagnostic](../hbase_266/token_probe_result.json) tried
  to obtain a token and received `UnknownProtocolException` because this
  simple-auth cluster has no registered `AuthenticationService`. The exact
  guard did not run. HBase's compiled `TokenProvider` also rejects SIMPLE
  authentication for token generation. This check remains untested by the
  real-RPC fault campaign.

## Interpretation limits

The selected checks were only those reached by the configured healthy
workloads. Solr exposed 11 such mapped server guards, ZooKeeper 28, and HBase
32. The experiments inject node crash/reboot at instrumented method points,
including request-processing paths; they do not yet inject packet drop or
delay on a specific RPC message. Message edges require correlation. Solr
node-to-node forwarding and unversioned state read-from relations remain graph
gaps. HBase's long-running server background work can shift root invocation
counters, leaving four checks without a strict full match. A separately
labeled `shape_occurrence` rerun of draws 2, 4, 8, and 9 produced eight full
matches in eleven fault trials. All eight reached their target guard, none
executed the mapped throw, and two stopped at the transient
`PleaseHoldException` before completing the workload. The eight shape-matched
actions and three exact actions in those runs are [audited separately](../hbase_266/audit10_shape.json)
and are not added to the strict table.
