# SOLR-14 graph-optional successor

This case keeps the existing Solr 8.11.4 `SplitShardTest#doTest` cluster JUnit
and the selected `SplitShardCmd.split@165:branch:5` check. The previous v30
healthy trace passed one JUnit and reached the exact check three times on
named `node1`. Its same-actor `SolrZkClient.exists` call at line 164 was
observed before the check. The call can throw a typed
`KeeperException.ConnectionLossException`. Source inspection shows that such
an exception exits that particular split invocation, so postfault target
retention is uncertain and must be reported separately.

The immutable `full-v1` package required a nonempty event-time graph path
before admitting fault doors. This successor sets
`require_event_time_paths=false` and `allow_local_timeline_doors=true` in
both healthy and full configurations. The fresh healthy gate still requires
one passing JUnit, valid loaded-class attestation, a named exact target, and
an exact typed line-164 door on the same named node and split occurrence
before a subsequent selected check. Graph edges and postfault target
retention are recorded as outcomes. No graph edge is inferred solely from
time order.

`run_campaign.py --mode healthy --preflight-only` and `--mode full
--preflight-only` verify the pinned source, compiled class, agent, adapter,
site rules, runner, and frozen core without starting a JVM. Dispatch must
create a matching case-local `admission-healthy-node2.json` receipt before
the healthy run. A separate matching `admission-full-node2.json` receipt is
required for the full run after the fresh healthy result passes the gate.
The full budget is 80 fault trials or 3600 seconds, with at most three
faults per trial. Outputs are distinct from `full-v1`; both node2 lane3 and
the shared Solr source lock remain held by the worker.

This is a staged package, not a completed campaign or bug finding. The
historical v30 trace is a source and instrumentation precedent; runtime
admission depends on a new healthy seed under this exact configuration.
