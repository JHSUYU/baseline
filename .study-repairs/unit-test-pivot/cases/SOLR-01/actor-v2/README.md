# SOLR-01 actor-aware V2

This directory is an independent successor to the historical `independent/`
campaign. Its 80 coarse trials are preserved there and do **not** count toward
the V2 budget. The workload remains the unchanged Solr 8.11.4
`CloudHttp2SolrClientTest#testAliasHandling` on the original embedded
three-Jetty cluster. The selected production check is
`BaseHttpClusterStateProvider.getAliases(boolean):267`.

## Runtime actor join

The Java agent changes bytecode in memory; it does not edit the test or Solr
source files. At `getRandomClient()` return, it records the actual
`CloudHttp2SolrClient` object and its `Http2ClusterStateProvider` object.
The selected `getAliases` entry, `LISTALIASES` I/O point, and selected outcome
record the provider object identity. Injection requires that this provider is
the exact one bound to the selected test client. The optional
`BaseCloudSolrClient.request` entry hook produced no event in these original
healthy runs, so it is not used as an actor proof. Source review shows the
test calls the selected client, whose alias resolution passes through
`BaseCloudSolrClient.resolveAliases` and
`BaseHttpClusterStateProvider.resolveAlias` to this `getAliases` call. The
runtime proof is the selected client/provider object binding at
`getRandomClient`, the concrete provider on each `getAliases` entry and
check, and each I/O inside that same active provider call.

`JettySolrRunner.getNodeName()` records the live-node name and its
`getSolrHome()` basename (`node1`, `node2`, or `node3`). The I/O hook receives
the loop's actual node name and computed base URL. It verifies that the URL
corresponds to that node name and maps it to a unique `JETTY/nodeN` role.
Unbound or ambiguous clients, node names, roles, and endpoint URLs cannot
consume a fault. Raw client/provider identities, node names, URLs, and Solr
homes remain in each trace for independent review. The two fresh healthy
clusters placed the first request on different physical Jetty roles, so the
cross-run selector names the **attempt-relative role** (`JETTY/attempt1`,
`JETTY/attempt2`, etc.). In each actual run the hook resolves this role only
after verifying the unique concrete `JETTY/nodeN`, live `nodeName`, and
computed base URL. Trial audit requires all ordered faults to belong to the
same client/provider, thread, and `getAliases` invocation, and to distinct
physical nodes. The selector also includes the production callsite/resource,
call ordinal, attempt ordinal, and exception kind.

The actual HTTP request can still succeed or fail normally when no fault is
selected. An injected exception at this callsite exercises the production
catch-and-fallback path. A selected throw after all live nodes fail is a
candidate observation; source review is still required to call it a bug.

## Build and calibration

Run `python3 build_v2.py`, then `python3 smoke_v2.py` before using a JVM
cluster slot. The build receipt locks the original Solr revision, original
test source/class, Solr JARs, V2 agent SHA, and classpath. The offline smoke
transforms four unchanged classes and verifies that wrong receiver, wrong
destination, wrong physical URL, ambiguous role, and wrong fault kind cannot
match. It does not launch the cluster.

After a cluster slot is assigned, `python3 calibrate_v2.py` runs **two fresh**
unfaulted original JUnits in `healthy-01` and `healthy-02`. It requires both
to pass and audits raw client/provider and all three Jetty bindings. The
calibration receipt locks trace hashes, the agent, and runner/controller
sources. If either run or actor join fails, no fault campaign starts.

`python3 campaign_v2.py` then starts or resumes V2 trials. It selects only
points observed before the same target check in both healthy runs, extends
each fault sequence with points actually exposed before that check in the
preceding faulted execution, and combines actor-bound I/O novelty with
JaCoCo production coverage. A trial is **effective** only when every planned
fault applies in order and the same selected check occurs after the last
fault. The budget is 80 effective trials with at most 8 faults per sequence
and a 320-selected safety cap. New coverage or I/O families in the last eight
effective trials extend the budget to 128 effective, max 10 faults, and 512
selected. Each selected trial has raw events, JaCoCo data, JUnit log, fault
plan, timing, and an atomic checkpoint; restart continues at the next
uncompleted sequence.

**Completed state:** final agent `bc52bf53...` passed offline wrong-actor,
wrong-endpoint, ambiguous-node, wrong-fault-kind, and relative-attempt smoke.
The unchanged JUnit passed on healthy-07/08 in 14.560/14.861 seconds.
Each trace has one selected client/provider binding, all three Jetty bindings,
36 provider entries/checks, and 15 `LISTALIASES` I/O points. Their independent
trace and JaCoCo hashes are in `calibration-receipt.json`; earlier healthy
runs remain diagnostic evidence, including a rejected retransformation
experiment that failed JVM verification and never entered the fuzz budget.
The healthy intersection supplied 30 attempt-relative root plans. The
resumable campaign finished 80 strict, post-final-target effective trials
and exited its tmux session naturally; its checkpoint retains 20 unselected
frontier plans. The last eight effective trials added no new production
coverage or stable I/O family, so the conditional extension did not apply.
The result mirror exited after its final atomic update.

The independent `audit_v2.py` recomputes injection and target outcomes from
each saved plan and raw event stream. `review_v2.py` compares selected throws
with the original source's all-endpoints-failed fallback and the live-node
snapshot from the same invocation. `coverage_v2.py` reports production method
and branch coverage from the two final healthy JaCoCo files plus effective
trials. For offline JaCoCo analysis it recreates the target and Jetty class
bytecode using the frozen agent transformer. JaCoCo's class ID for
`BaseCloudSolrClient` matches its original Solr JAR bytecode, and the healthy
runs emitted no `REQUEST_ENTER`; the class was evidently loaded before that
transformer registered. The analysis therefore uses its original bytecode. This
combination yields zero unmatched production classes and counts the selected
`getAliases` branch, whereas analysis against only the original target JAR
would omit it. These post-run scripts do not alter the active campaign or
its locked runner sources.

Final raw audit: 80/80 strict and effective, zero discrepancies. JaCoCo
production coverage gained 9 methods and 60 branches, including two branches
in the selected `getAliases` method. All 45 selected throws followed injected
failures at all three live endpoints of the same provider invocation. A
separate clean replay of trial 4 reapplied all three faults and reproduced
the original JUnit exception. Original source at line 267 defines this as
the all-endpoints-failed fallback; no new bug is confirmed here.
