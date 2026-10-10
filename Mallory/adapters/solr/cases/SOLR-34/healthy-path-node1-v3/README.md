# SOLR-34 path-aware healthy seed on node1

This package runs the unchanged Solr 8.11.4 cluster JUnit
`TestCoordinatorRole#testSimple` once. The test starts four ordinary nodes,
adds a fifth coordinator, sends a query through it, and checks the synthetic
collection. The selected check is `CoordinatorHttpSolrCall.getCore` line 139;
the selected newly constructed `SolrException` is line 143. The rethrow at
line 140 is a separate outcome.

The healthy trace can reach the coordinator's synthetic collection creation
while the selected inner check stays absent: line 139 executes only after the
subsequent local cluster-state lookup still returns null. This package
therefore reports a target-absent bootstrap explicitly. A passing JUnit or an
unrelated exception does not establish that the selected check fired.

The only configured fault door is the typed retry-internal
`SolrZkClient.lambda$getData$6` call to `SolrZooKeeper.getData` at line 349.
The pinned path-aware agent records its first String argument. The healthy
audit requires a `ConnectionLossException` door with the exact
`/collections/.sys.COORDINATOR-COLL-conf/state.json` path on the named fifth
coordinator actor, together with a passing JUnit, loaded class hash, and
loaded target and door catalog. It reports separately whether an exact
line-139 check follows that door on the same actor. A target-absent result
does not admit a target-retaining full campaign without further evidence.

Offline checks: `python3 static_preflight.py` and
`python3 -m unittest discover -s . -p 'test_*.py'`. The path-aware agent
release `b4bb6493...` must be synced to node1 with its pinned hash before
the node1 preflight. Dispatch supplies `admission-healthy-node1.json` GO;
only then does `run_node1.sh` start one fault-free JUnit. After it finishes,
run `audit_healthy.py` on the configured output. No GO receipt or runtime
result is included in this package.
