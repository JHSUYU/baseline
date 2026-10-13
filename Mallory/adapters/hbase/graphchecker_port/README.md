# HBase 2.6.6 GraphChecker protocol port

This overlay installs source hooks for the original HBase MiniCluster JUnit
tests. It is confined to `Mallory/adapters/hbase/graphchecker_port` until
explicitly applied to an isolated HBase 2.6.6 checkout. It does not reuse the
old Mallory `Probe` graph.

## Install in an isolated source checkout

1. Build and install `Mallory/graphchecker-runtime` as Maven artifact
   `edu.uva.liftlab.mallory:mallory-graphchecker-runtime:1.0-SNAPSHOT`.
2. Run `python3 apply.py --check /path/to/hbase-2.6.6`, then
   `python3 apply.py /path/to/hbase-2.6.6`. The command refuses already
   modified anchors and writes only after all source inputs validate.
3. Build the patched HBase `hbase-protocol-shaded`, `hbase-procedure`,
   `hbase-client`, and `hbase-server` modules with their reactor dependencies.
   The script adds the Mallory runtime dependency to client, procedure, and
   server POMs and copies the GraphChecker bridge classes into those modules. Keep the resulting
   patched jars together; do not mix them with the unpatched 2.6.6 jars.
   HBase 2.6.6 requires a Java 8 Maven build here. The JUnit launcher must
   match the distribution's JUnit Platform 1.13.4 jars.
4. Run the unchanged
   `org.apache.hadoop.hbase.client.TestConnectionImplementation#testMetaLookupThreadPoolCreated`
   through `edu.uva.liftlab.mallory.hbase.graphchecker.SelectedJUnitGraph`,
   passing the test class and method as arguments. Put patched HBase jars and
   `mallory-graphchecker-runtime` before stock HBase distribution jars on the
   classpath, and set `MALLORY_GC_TRACE=/path/to/trace.jsonl`.
   The runner records MiniCluster startup and the test body in one window;
   use a fresh JVM and the pinned classpath per trial.

## Boundaries and evidence

The request envelope uses HBase's existing `RequestHeader.attribute` field.
`Call` construction captures the caller scope before a sender-thread handoff.
MiniCluster thread constructors register the exact master/RegionServer objects
using their explicit constructor indices. `Call` also registers itself as an
alias of the current client source before its asynchronous send.
The dedicated master and RegionServer threads enter an actor scope while their
original `run()` executes. HBase's client `ThreadPoolExecutor` captures the
submitting scope for each task and restores it around that task's `run()`.
This covers asynchronous meta scans without attributing unrelated worker
threads from their names.
Netty confirms a request SEND only on successful `ChannelFuture`; the blocking
client confirms it after `IPCUtil.write` returns from its flush. The server
installs the request context while `CallRunner` executes. A new optional
`ResponseHeader.mallory_graph_context` field carries the response's context.
Netty confirms response SEND only on successful write future, and the Simple
server confirms it after the complete response buffer has been written.
`RpcConnection.readResponse` installs the received context only after it has
found the matching live `Call`; unknown or timed-out calls create no RECEIVE
edge. The GraphChecker correlation ID is a deterministic name UUID derived
from the registered client source, RPC method, actual HBase call ID,
and attempt. Duplicate replay keys get an explicit collision ordinal and a
`RPC_REPLAY_KEY_COLLISION` gap. A call without a registered source is left
unattributed with `RPC_REPLAY_KEY_MISSING` instead of inventing a replay key.

The optional Netty SASL overlay carries a separate envelope in each client
SASL response frame, before normal RPC headers exist. The server strips that
envelope before `SaslServer.evaluateResponse`, so the SASL mechanism receives
the original token bytes. A captured call-thread scope gives the connection a
stable source and correlation key; the frame's response ordinal is its attempt
ID. A successful Netty write confirms SEND, and the server enters RECEIVE
only while evaluating that exact frame. An unregistered source sends the
original SASL bytes and records a gap. This covers the authentication phase
used by `AuthenticationTokenSecretManager.retrievePassword`, including the
HBASE-34 check's transport phase. The frame format and exact source are
compiled and verified in a focused round-trip smoke. The unchanged secure
`TestGenerateDelegationToken#testOnlyToken` JUnit also passed with the
isolated overlay: its trace had eight prepared SASL frames, eight confirmed
EXPORTs, eight server ATTACHes, and TrialGraph reconstructed eight ordered
`hbase-sasl.REQUEST` WIRE edges. This is a protocol-only pilot: the target
check was not woven, and the ZooKeeper key update to `allKeys` has no exact
observed state version yet. It is not an HBASE-34 case result. Blocking SASL and
server-to-client SASL challenges are outside this overlay. The SASL frame
extension requires both ends of the isolated test cluster to use this patch;
the patched client is not wire compatible with an unpatched SASL server.

`BlockingRpcCallback.run()` publishes its `result` and `resultSet` under the
callback monitor. The overlay records a `WRITE` of that callback's unique
one-time version before `notifyAll()`. `get()` records the matching `READ`
under the same monitor after observing `resultSet`. This is the precise
cross-thread result handoff used by blocking HBase RPCs. Reaching a later
check through nested scanner calls also requires a proven return dependency
from the child call back to its caller. A scope edge alone does not prove that
the caller consumed the returned value.

The first verification gate should check that one exact request and response
pair has matching correlation/attempt on named client and server sources,
that `sent` is absent for a failed write, and that the original JUnit target
is reached after a successfully applied fault. A passing JUnit alone is not
causal-graph evidence. The two-phase `MessageDoors.prepareOutbound`/`sent`
API is required; a header preparation is not a proven SEND.

The callback edge is limited to the callback's synchronized publication.
The updated overlay also observes the `hbase:meta` table-state Cell. After
`MetaTableAccessor.updateTableState` receives a successful `Table.put` return,
it records a WRITE of that Put's actual Cell version. Synchronous and
asynchronous `getTableState(Result)` record a READ only after parsing the Cell
returned by the Get. The version key uses the Cell's row, family, qualifier,
timestamp, type, and value digest. GraphChecker connects WRITE to READ only
when a unique observed writer has the identical version; a missing source,
missing writer, or duplicate version remains an explicit gap. This hook covers
the table-state column, not every `hbase:meta` field. A direct writer outside
the `MetaTableAccessor` API must be instrumented before its reads can be
treated as fully explained.

`ProcedureExecutor` now captures the submitting request scope for a root
procedure and for each child procedure, then restores it around each worker
execution. This is a general HBase procedure handoff; it is needed because
the table-state WRITE often runs on a master procedure worker rather than the
master's main thread. Procedures recovered from durable storage without an
observed submission remain unattributed. The JUnit runner still emits its
general `STATE_VERSION_UNHOOKED` gap for other state families; do not treat
that gap as proof that the table-state Cell hook failed. Likewise, if a
server/client source is not registered, do not infer it from thread names.

An isolated diagnostic on the unchanged
`TestConnectionImplementation#testMetaLookupThreadPoolCreated` passed and
observed a master WRITE and client READ with the same table-state Cell version.
TrialGraph placed their STATE edge in the target check's backward closure.
This diagnostic overlaid the new source hooks on an older full weave; it is
not an accepted static-scope campaign. A fresh exact-classpath HBASE-02 scan,
full weave, and unchanged healthy JUnit subsequently passed with the same
versioned STATE edge in the target closure. The scan selected the controlling
branch at `ConnectionImplementation.relocateRegion` line 910/unit 8 and the
`TableNotEnabledException` throw at line 911/unit 17, with 612 typed doors.
The healthy run observed the branch once and did not throw. Fault trials under
this fresh weave and a terminal campaign receipt are still required before
counting HBASE-02 as complete.
For HBASE-01 specifically, `ConnectionImplementation.isDeadServer` reads
`ClusterStatusListener.deadServers`; `receive(ClusterMetrics)` adds to that
list on the multicast listener path. Soot marks both sites as possible state
accesses, but the current runtime has no observed collection-element version
or transported multicast context. The meta-scanner RPC closure therefore
does not prove the dead-server predicate's cross-thread input. This remains a
quality gap even if a faulted trial reaches the target check.

An initial full-scope `testMetaLookupThreadPoolCreated` run exposed two general
graph gaps: a transported header exceeded the runtime's size limit, and the
scanner's nested return was absent from the target's backward closure. The
generic runtime now uses a compact transport identity and a validated child
completion receipt. On an unchanged-JUnit diagnostic run with those changes,
the target's backward closure contained 11 observed fault-door site IDs,
including the scanner RPC path; `WIRE_HEADER_INVALID` and
`REGION_COMPLETE_UNPROVEN` were both zero. This diagnostic used an older
static manifest. The strict campaign must use a new matching static manifest,
weave receipt, and native fault receipt before a case is counted.

`test_apply.py` checks the source anchors and confirms the successful-write
boundaries are present in the generated patch. It does not replace an HBase
build or a MiniCluster trace run.

## Prepare another HBase checklist case

`prepare_case.py` reads one HBase row from
`data/mallory/graphchecker_port/final-results.tsv`. It takes the named throw
and original JUnit method from that row, runs the Soot scope planner on the
same patched HBase bytecode, and writes a campaign config only when the
planner finds an exact controlling branch and a throw of the listed class.
It also verifies both sites against the inventory class and method, and the
throw against the listed source line. If several branches guard the same
throw, `--check-line` selects the source line of the intended guard; it never
selects an I/O or fault door.
The generated manifest supplies every region, coverage site and fault door;
the script contains no per-case I/O list.

```sh
python3 Mallory/adapters/hbase/graphchecker_port/prepare_case.py \
  --inventory data/mallory/graphchecker_port/final-results.tsv \
  --case-id HBASE-02 \
  --scope-template /path/to/pinned-scope-input.json \
  --campaign-template /path/to/pinned-campaign-case.json \
  --planner-classpath /path/to/planner-classpath.txt \
  --output /path/to/new-case-preparation
```

The scope template's `analysis.process_dirs` must contain the compiled target
class, and its ordered `analysis.classpath` must be the same dependency
classpath passed to WeaveMain. The campaign template must refer to original
JUnit bytecode and the pinned runtime, weaver and runner. The script fails
before creating a campaign config if the target class, JUnit class, branch,
throw or classpath receipt cannot be verified. Each prepared case then needs
its own unchanged-JUnit healthy gate before fault trials. The HBASE-01 v3
merged bytecode lacks `hbase-zookeeper`'s `MasterAddressTracker`, so HBASE-37
needs that module included in a new exact static/weave input.
