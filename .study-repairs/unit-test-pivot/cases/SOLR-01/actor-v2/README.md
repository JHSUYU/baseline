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
`BaseCloudSolrClient.request` records the actual request receiver. The
`getAliases` entry, `LISTALIASES` I/O point, and selected outcome record the
provider object identity. Injection requires that this provider is the exact
one bound to the selected test client.

`JettySolrRunner.getNodeName()` records the live-node name and its
`getSolrHome()` basename (`node1`, `node2`, or `node3`). The I/O hook receives
the loop's actual node name and computed base URL. It verifies that the URL
corresponds to that node name and maps it to a unique `JETTY/nodeN` role.
Unbound or ambiguous clients, node names, roles, and endpoint URLs cannot
consume a fault. Raw client/provider identities, node names, URLs, and Solr
homes remain in each trace for independent review. Fault selectors include
the stable client actor, destination role, production callsite/resource,
getAliases I/O-call ordinal, attempt ordinal, and exception kind.

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

**Current state:** offline build and smoke passed. Healthy JUnit calibration
and V2 fault trials have not started while the shared Solr cluster JVM and
disk slot remain occupied.
