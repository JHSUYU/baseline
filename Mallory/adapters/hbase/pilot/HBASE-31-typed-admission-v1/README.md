# HBASE-31 typed healthy admission

This admission is scoped to `TestRegionMove#testDisableAndMove`. Its `@BeforeAll`
starts two RegionServers. The test moves a region through unassign, assign, and
disabled-table failure checks. The target is the server-side start-code guard in
`RSRpcServices.throwOnWrongStartCode(long)` at line 2010, with the mismatch throw
at line 2011. A normal check with matching start codes does not show a bug.

The staged configuration pins the one client-side door at
`RSProcedureDispatcher.ExecuteProceduresRemoteCall.sendRequest` line 513, where
the compiled method invokes `AdminService.BlockingInterface.executeProcedures`.
`buildOpenRegionRequest` sets the request start code from `ServerName` at line
529; the server's `executeProcedures` checks it before procedure execution.
The compiled class and JAR hashes, source commit, core release, agent, adapter,
and test runner are verified by `preflight.py`. The adapter JAR SHA-256 is
`ab943e3fda02126261f99703cafeb4b6b0f71b6b5d645a29abb3498d43851cd1`.
Node1's source files match the pinned commit's selected files, but its `.git`
pointer is detached from the missing Git object directory. The node1 runner
explicitly enables detached-source mode; it still checks the three selected
source hashes and both compiled class hashes. Node0 checks the Git commit.

The old broad-door healthy trace (`data/mallory/calibration_v2/HBASE-31`) passed
JUnit 1/0/0 and reached the exact nonthrowing guard 16 times on `rs0` and
`rs1`. It does not prove that this one typed door has an event-time path to
the check. The new pilot therefore uses a fresh output directory and the
pinned `fa5f3bde...` core with `require_event_time_paths`,
`reject_coarse_roots`, and `auto.io.doors: false`.

Run the offline check with:

```sh
python3 Mallory/adapters/hbase/pilot/HBASE-31-typed-admission-v1/preflight.py
```

After dispatch grants a free node1 lane, the single healthy-only run is:

```sh
MALLORY_HBASE31_NODE1_GRANT=healthy-only \
  Mallory/adapters/hbase/pilot/HBASE-31-typed-admission-v1/run_healthy_node1.sh
```

`verify_healthy.py` requires selected JUnit success, the exact loaded target
class hash and one loader, a named `master0` typed door, a named `rs0`/`rs1`
nonthrowing check, and a strict observed RPC edge path with increasing event
sequence. It recomputes the witness from the raw healthy trace using the
pinned graph release. The verifier records a SHA-bound verdict in the campaign
directory. A path failure is a failed admission, not a target exception.

This healthy admission does not authorize fault or full replay. An injected
`IOException` at the pre-send door skips that RPC, so target retention after
injection needs its own causal pilot. No bug claim follows from this healthy
run or from the historical calibration.

## Fresh healthy v1 result and scoped repair

The node1 v1 run passed the selected JUnit 1/0/0. It observed 16 nonthrowing
checks on named `rs0` and `rs1` with the pinned loaded target class hash and
eight typed `@513` doors on `RSProcedureDispatcher-pool-*` threads. Every door
was attributed to `unknown`, so the campaign ended
`healthy_no_injectable_door` and the strict audit failed. The raw trace has
eight ordered door, RPC send, matching-token receive, and target-check
sequences. These observations are preserved in `healthy-v1-negative-receipt.json`
and the copied `data/mallory/calibration_v31_typed/HBASE-31` archive; they do
not establish a qualifying named path.

The case-local v2 overlay scopes only
`ExecuteProceduresRemoteCall.sendRequest` to the already registered
`this$0.master` object. It accepts a `masterN` identity and otherwise leaves the
worker unknown. It does not change the base adapter's RPC token propagation,
the selected JUnit, the target guard, or the one typed door. The immutable
overlay JAR SHA-256 is
`a8ddd472a72345b43d9f382ffd0cf36aae7d3aa461db264fb2e5498735e44e20`.
Three Maven tests cover exact bytecode transformation, null and wrong owner,
worker thread binding, and scope exit. Three frozen-trace graph tests check a
matching request token, wrong token, and different producer thread. The
matching-token graph test models the missing master binding; only a fresh
MiniCluster run can verify that the runtime hook supplies it.

Run the v2 offline preflight with:

```sh
python3 Mallory/adapters/hbase/pilot/HBASE-31-typed-admission-v1/preflight_v2.py
```

After a separate dispatch grant for v2 on node1, run only:

```sh
MALLORY_HBASE31_NODE1_GRANT=healthy-v2 \
  Mallory/adapters/hbase/pilot/HBASE-31-typed-admission-v1/run_healthy_v2_node1.sh
```

The v2 healthy run passed JUnit 1/0/0 and produced eight named `master0`
typed-door paths to the exact nonthrowing guard on `rs0`/`rs1`; the strict
audit and independent raw-trace verifier passed. The pinned verdict and hashes
are in `healthy-v2-admission-receipt.json`. `diagnostic-pilot-review.json`
records one source-backed, ordinal-1 `IOException` candidate for a separate
admission decision. That exception is injected before send. HBase can schedule
a delayed retry, but the current adapter does not observe that retry queue's
task handoff. A later target check would require a strict postfault path to
qualify; a fault or full campaign has not been launched here.
