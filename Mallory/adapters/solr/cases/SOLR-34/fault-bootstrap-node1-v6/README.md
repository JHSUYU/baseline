# SOLR-34 node1 bounded fault bootstrap, v6

The v5 healthy run passed JUnit 1/0/0 but stopped before fault trials because
its configured selected throw was `@143:throw:1`. The actual loaded agent
catalog has `@139:branch:6`, `@140:throw:1`, and `@143:throw:2`.
The raw v5 output remains untouched. This v6 package pins a copy of the
five-line loaded catalog (SHA-256
`f84a68f116d42f6ccf9c316edcdcf793174eded0b899bd381f1dfec5b45e3503`)
and verifies every target, region, and door ID, the original class hashes,
single class loader, and typed resource argument before a JVM can start.
The agent JAR bytes are identical to v5; the case-local release manifest,
config, pilot, and output path have new v6 pins.

The selected workload is the unchanged Solr 8.11.4 cluster JUnit
`TestCoordinatorRole#testSimple`. Its healthy v4 run passed 1/0/0 and saw nine
typed reads of `/collections/.sys.COORDINATOR-COLL-conf/state.json` on node5,
but did not execute the throw-only `CoordinatorHttpSolrCall.getCore` guard at
line 139. Historical CrashFuzz fault runs reached this guard, so this package
explores fault-driven reachability without claiming a healthy target closure.

The sealed v4 trace yields six request-thread path reads (node5 ordinal
5, 15, 16, 18, 19, 20) within one `getCore` region interval, sharing a trace
root with a Solr HTTP send and receive. The three node5 ZooKeeper callback
reads (17, 22, 23) are excluded. The HTTP witness and interval support
operation membership; they do not prove every Overseer hop is causally traced.

The case-local agent checks the exact path in `point.resource` **before**
emitting `FAULT_MATCHED` or applying the exception. A wrong path leaves the
fault unconsumed. The controller selects only method-qualified `getData`
reads with the resource, named actor, epoch, request thread, and operation
witness. A subsequent fault must remain in the same observed `getCore`
occurrence. Each trial checks the applied fault's path/context and asks whether
the exact line-139 check followed it in that same occurrence. Line 140's
prior-exception rethrow and line 143's newly constructed exception are
reported separately. A target observation stops the bootstrap for source
review; it is not a new-bug classification.

Budget: one fresh healthy run plus at most 12 fault trials, 2400 seconds,
two exception faults per sequence, 480 seconds per trial. The target-absent
phase explores up to six selected doors per trial. No graph-guided phase is
entered by this package. The output directory is fresh and resume-capable in
the frozen controller. The run requires dispatch's matching node1 GO receipt,
node1 lane locks, and the existing free-space and memory gates.

Static check: `python3 static_preflight.py`. Offline tests:
`python3 -m unittest -v test_bootstrap_policy.py test_pilot_wiring.py
test_sealed_v4_witness.py test_catalog_identity.py`. These do not run the Solr JUnit. The admission
request has `go=false`; dispatch alone creates the separate GO receipt and
launches `run_node1.sh` after lane assignment. Do not mark the checklist from
this stage.
