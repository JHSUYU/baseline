# HBase protocol adapter for the original GraphChecker runtime

This isolated adapter applies to an unmodified HBase 2.6.6 source checkout at
commit `d5f63f523c065f963992ea4e74db268d17816631`. The selected JUnit
source is unchanged. `apply.py --check SOURCE` verifies all 29 source anchors
before `apply.py SOURCE` writes anything. The bridge depends on the
source-built `org.example:GraphChecker:1.0-SNAPSHOT` artifact, whose
`MessageDoors`, `RowRuntime`, and `CausynthTraceRecorder` are the original
GraphChecker implementations.

The HBase RPC request context travels in `RequestHeader.attribute`; the
response context travels in the added optional `ResponseHeader` field. The
SASL context travels in an envelope around each client SASL response frame;
the server removes the envelope before passing the original token to the
SASL mechanism. A correlation contains the registered source, actual HBase
call ID or SASL connection ordinal, and attempt. The server calls the original
`MessageDoors.inbound` only after receiving the matching physical request or
SASL frame. The response is installed only after the client finds its live
HBase `Call`. MiniCluster actor registration and executor/procedure scope
handoffs remain source hooks, not thread-name inference.

The original runtime requires the transport name to be uppercase for its
sender lookup. Requests use `MessageDoors.outboundRequest` with the correlation
and attempt physically carried in the message as the producer site. This
separates asynchronous requests that share a daemon tick. If two HBase client
instances reuse a call ID, the adapter records `RPC_REPLAY_KEY_COLLISION`;
the gap is blocking and the second call carries no GraphChecker header.
If multiple SASL connections reuse the same source and service identity, the
adapter likewise records a blocking `SASL_REPLAY_KEY_COLLISION` and leaves
later connections without a graph envelope; a local connection ordinal is
not a replay-stable identity under concurrent creation.

The original `MessageDoors.outbound` records a SEND when the header is made
immediately before a transport write attempt. It cannot defer the SEND until
Netty confirms the write. A failed write has no matching inbound event and
records `HBASE_SEND_ABORTED` through original `RowRuntime.gap`; such an
unmatched SEND is not a causal delivery. This adapter intentionally makes no
two-phase API change to the original runtime. If a native session shows a
false delivery, that is evidence to revise this boundary.

`GraphCheckerHBaseMetaState` observes the actual `hbase:meta` table-state
Cell written by an acknowledged Put and returned by a Get, naming its row,
family, qualifier, timestamp, type, and value digest. It calls original
`MessageDoors.stored/fetched` with that physical identity. Original
`MessageDoors.fetched` creates a causal notification edge only inside a
`MessageDoors.notified` callback; an ordinary table Get is not thereby an
exact read-from relation. The adapter emits the blocking
`HBASE_META_STATE_READ_FROM_UNPROVEN` gap for that ordinary Get. Native
field/value rows still require the original
Soot/VM instrumentation and `RowRuntime` evidence. Do not count this Cell
observation alone as a complete HBASE-02 target closure.

`NativeHBaseJUnitRunner` opens an original GraphChecker session and trace
window, invokes one unchanged JUnit method through the JUnit Platform
Launcher (including HBase's `@TestTemplate` methods), then closes
the session. It fails unless exactly one test executes successfully. Build
this runner against the pinned GraphChecker and HBase test classpath, and
run in a fresh JVM with `CAUSYNTH_TRACE_OUTPUT_DIR` and
`-Dcausynth.concolic.results` set to trial-specific paths. A healthy
protocol/session proof must inspect original `runtime_trace.jsonl` and the
original session manifest for matching request/response and SASL identities,
source attribution, and explicit gaps before any fault trials.
