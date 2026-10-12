# SOLR-14 case-local full campaign stage

The selected Solr 8.11.4 target is `SplitShardCmd.split` line 167, reached by
`SplitShardTest#doTest`. The exact check is line 165. The v30 healthy run passed
one JUnit and reached that check three times on named `node1`. Its trace
observed the line-164 `SolrZkClient.exists` call in the same split occurrence.
The v38 adapter scopes `OverseerCollectionMessageHandler.processMessage` to
its owning `CoreContainer` actor; the new healthy run must verify this binding
again. The v41 source review shows that a `ConnectionLossException` thrown at
line 164 exits this split invocation before the check. Target retention after
injection and graph/path evidence are campaign outcomes, not launch gates or
bug claims.

`config-healthy-node2.json` stages a fresh direct cluster JUnit calibration.
The separate full run is admitted only when that healthy result passes exactly
one JUnit, reaches the exact check on a named actor, has valid runtime
attestation, and observes an injectable `ConnectionLossException` at the real
line-164 ZooKeeper call on a target actor. `config-full-node2.json` then runs
its own healthy seed and up to 80 fault trials, 3600 cumulative trial seconds,
and three faults per trial. It uses exception I/O faults and the frozen v41
graph-order core; the core's own healthy attestation also gates fault trials.

The package pins the immutable numeric-thread agent, v38 Solr adapter, exact
site catalog, Solr source and compiled target hashes, direct JUnit runner,
and frozen core manifest. It uses the node2 lane3 source checkout and holds
the lane3 and shared Solr source locks. The shell enforces disk and RAM floors.
`admission-healthy-node2.json` and `admission-full-node2.json` are intentionally
absent. Dispatch must write matching `go=true` receipts to start either JVM
campaign. `admission-request.json` records the two planned outputs and
`go=false`. No JVM was started while staging this package.

Run a no-JVM preflight on node2 with `python3 run_campaign.py --mode healthy
--preflight-only` and repeat with `--mode full`. After dispatch schedules the
lane, `run_node2.sh healthy` runs the fresh seed; `run_node2.sh full` checks
the completed seed and starts the conditional full campaign.
