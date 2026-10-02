# Four-system graph-guided fault and coverage baseline

This experiment uses the pinned releases HDFS 3.4.3, HBase 2.6.6,
ZooKeeper 3.8.7, and Solr 8.11.4. GraphChecker `main` was fast-forwarded to
`4027318f5` for its latest reference code and runtime identity design. The
candidate decision files came from the local GraphChecker classifier output;
each `selected10.json` records that input file's SHA-256. The baseline remains
a separate concrete JVM agent and Docker harness.

## Pipeline

1. Read the classifier's `YES` checks. `map_candidates.py` maps each explicit
   source throw to its compiled `method#L<line>` throw and a directly guarding
   `method#B<n>` conditional branch. Indirect or ambiguous mappings are
   rejected.
2. Run a healthy workload with branch probes over the mapped methods. Keep
   only guards actually executed inside the workload time window on a server
   JVM. Draw ten targets per system with a fixed seed and save the exact site
   IDs and bytecode locations in `selected10.json`.
3. For each target, start a fresh cluster, verify a healthy seed with an
   independent checker, then mutate observed fault points. A controller can
   kill or restart only one of the experiment's named containers. Fault
   matching is armed after preparation and frozen before the checker.
4. Build a per-run graph from method calls/returns, task handoffs, correlated
   messages, and observed field accesses. State edges without an observed
   version are explicitly `STATE_CANDIDATE`. Count code blocks and branch
   outcomes globally and within the target's backward closure. Rank mutations
  using closure proximity, new graph features, coverage, and recovery points.
5. Record a target exception candidate only when the mapped throw actually
   executes after a complete injected sequence and its replay confirms it.
   Review the operation's preconditions and expected API errors before calling
   any candidate a new bug. Workload errors, checker failures, and exceptions
   elsewhere remain separate observations.

The broad coverage channel records first hits per JVM for basic blocks and
conditional branch outcomes. Preparation events are excluded from workload
feedback, so a broad hit that occurred during preparation and repeats later
may be absent from the workload count. Detailed target-region branch probes
do not use that first-hit filter. Switch arms and exception edges are not
included in the branch metric.

The controller's strict replay identity is `(node, epoch, site, context,
ordinal, phase)`. It records the observed identity and `exact` match mode for
every injected action. An optional `shape_occurrence` mode drops activation
counts from the context while retaining the call/async path and local site
occurrence; these four-system campaigns leave it disabled. This is a baseline
method-level identity. It does not claim to reproduce GraphChecker's region
occurrence address or recursive message-anchor identity.
The JVM agent's root invocation counters start at process boot; they are not
reset when the workload is armed. HBase background work can therefore shift
otherwise equivalent contexts across trials. The strict campaign keeps such
actions unmatched. A separately labeled `shape_occurrence` rerun can test
those sites with weaker identity guarantees, never counted as an exact match.

The HBase agent correlates its Netty RPC endpoints by socket and call ID. The
ZooKeeper 3.8.7 adapter correlates a client send with server request processing
by session ID and xid; a single client request may lead to several server-side
processing events. Solr correlates workload HTTP sends and `HttpSolrCall`
receives with a request header. Solr's internal node-to-node forwarding is
currently a graph gap; no inferred edge is silently treated as exact.

## Selection sizes

| System | Classifier YES | Direct bytecode mapping | Guards reached on a server during workload | Drawn |
| --- | ---: | ---: | ---: | ---: |
| HDFS 3.4.3 | 532 | See `../hdfs_random10/mapped10.json` | See HDFS pilot | 10 |
| HBase 2.6.6 | 225 | 196 | 32 | 10 |
| ZooKeeper 3.8.7 | 119 | 98 | 28 | 10 + 1 reserve |
| Solr 8.11.4 | 375 | 305 | 11 | 10 |

The HBase `AuthenticationTokenSecretManager.retrievePassword` check around
`allKeys.get(keyId)` maps to bytecode, but the CRUD/snapshot workload does
not reach that token path. It is not part of the 32 dynamically reached
guards and must not be counted as tested by this campaign. The focused
[token RPC probe](../hbase_266/token_probe_result.json) reached the server but
received `UnknownProtocolException`: `AuthenticationService` is not registered
in this simple-auth pilot. The pinned `TokenProvider` bytecode would also
reject SIMPLE-authenticated token generation; it admits Kerberos, Kerberos SSL,
and certificate authentication. A secure HBase fixture with a registered
token service and a client using a token is required to test this check in a
real RPC path.

ZooKeeper draw 6 initially produced a replayable exact throw at
`FinalRequestProcessor.handleGetDataRequest` line 672. The first version of
the workload continued issuing `get /adhoc387` after its initial `create`
lost the connection to the crashed leader; the resulting `NoNodeException`
was the expected API response to a missing node. That raw trial is archived
under `../zookeeper_387/out_old_workload/`. The corrected workload confirms
the persistent parent exists before any get. Its rerun reached the guard after
a complete exact fault match, with no target throw and a passing checker.
Draw 7 was invalid because its healthy seed already threw at the target; a
deterministic reserve draw 11 supplied the tenth valid ZooKeeper check.

The default search budget for each new-system target is one healthy seed and
up to three fault trials, stopping after two complete matches. A partial or
unmatched sequence does not establish a fault effect. The HDFS ten-target
coverage experiment and its results are in `../hdfs_random10/COVERAGE10.md`.

## Reproduce

From `crashfuzz/`, after building `agent/` and providing the pinned release
archives under `~/.baseline-deps/`:

```sh
PYTHONPATH=src python3 examples/quad/map_candidates.py hbase
PYTHONPATH=src python3 examples/quad/map_candidates.py zookeeper
PYTHONPATH=src python3 examples/quad/map_candidates.py solr
PYTHONPATH=src python3 examples/quad/run_seed.py examples/hbase_266 --properties out_mapping/branch-discovery.properties --output out_branch_discovery
PYTHONPATH=src python3 examples/quad/run_seed.py examples/zookeeper_387 --properties out_mapping/branch-discovery.properties --output out_branch_discovery
PYTHONPATH=src python3 examples/quad/run_seed.py examples/solr_8114 --properties out_mapping/branch-discovery.properties --output out_branch_discovery
PYTHONPATH=src python3 examples/quad/run_candidates.py hbase
PYTHONPATH=src python3 examples/quad/run_candidates.py zookeeper
PYTHONPATH=src python3 examples/quad/run_candidates.py solr
PYTHONPATH=src python3 examples/quad/audit10.py hbase
PYTHONPATH=src python3 examples/quad/audit10.py zookeeper
PYTHONPATH=src python3 examples/quad/audit10.py solr
PYTHONPATH=src python3 examples/quad/run_candidates.py hbase \
  --variant shape --allow-shape-fallback --draws 2,4,8,9
PYTHONPATH=src python3 examples/quad/audit10.py hbase \
  --variant shape --draws 2,4,8,9
PYTHONPATH=src python3 examples/hbase_266/run_token_probe.py
```

The mapping commands require GraphChecker decision files at
`../GraphChecker/tools/coordination_classifier/out/<system>.decisions.jsonl`.
The frozen `selected10.json`, target properties, and `token_target.json` in
this repository are sufficient to replay the chosen campaigns without
regenerating those decision files.

The three new systems use disjoint `adhocfuzz-*` Docker networks and
containers. Each `results10.json` aggregates trial and oracle counts;
`out_campaign/` retains per-run results, traces, graphs recoverable from
traces, fault journals, and state for replay.
