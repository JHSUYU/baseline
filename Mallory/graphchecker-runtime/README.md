# Mallory GraphChecker runtime port

This module is a Mallory-owned copy of the GraphChecker occurrence and message
contract, adapted to original JUnit cluster workloads. It is independent of
the older Mallory event-graph implementation. Build with `mvn -q test install`.

`MessageDoors` records named source epochs, request/tick scopes, selected
regions and calls, target checks and throws, branch coverage, fault doors,
confirmed outbound messages, matching inbound headers, and versioned state
reads and writes. A prepared outbound is not an EXPORT until a successful send
or an actual matching receive confirms it. An inbound decoded inside an active
region attaches to that region without discarding its stack. Unknown source,
missing carrier, ambiguous version, and failed join produce explicit GAP rows.
For a queue consumer, a notified exact versioned read followed by `consumed`
joins the read occurrence to the processing scope through a HANDOFF edge;
the queue path, version, writer, and unique reader endpoint must agree.

`TrialGraphMain trace graph feedback targetSiteOrJsonArray [priorTrace|-] [staticScopeMap]`
builds NODE, WIRE, STATE, and local SCOPE edges from those rows. It admits an
edge only with a concrete producer identity and uses event sequence cutoffs
when walking backward from the target. Coverage and fault doors in a target
occurrence are included only if their row precedes that target check. A WIRE
join whose EXPORT follows its ATTACH is rejected. Feedback separates observed closure
nodes/edges/coverage/doors from `staticMay*` regions and doors. The latter are
conservative scheduling candidates produced by the Soot scope planner; they
are never reported as observed causal edges or coverage novelty.
`targetThrowClosures` also records a separate backward closure and sequence
cutoff for each attributed `TARGET_THROW`, so a fault linked to a check in one
request cannot be credited for a throw in another request.
For a JSON array of controlling check sites, feedback reports each site's
reach, outcomes, and closure, plus their union. A missing guard in one run is
recorded explicitly; short-circuit evaluation can legitimately skip it. The
throw event has its own exact closure and is never inferred from guard reach.

RPC headers carry a separate replay lineage derived from the sender's replay
occurrence and send ordinal. It can select the corresponding fault door in a
fresh JVM even when the concrete RPC correlation ID changes. Exact WIRE and
STATE joins continue to use the original per-trial IDs. A missing replay
header produces a gap and leaves the exact WIRE evidence intact.

Two completed root scopes on the same concrete JVM thread and registered
source, using the same API, have a `PROGRAM_ORDER` edge when the first scope's
matching exit precedes the second entry. The entry and exit carry the same
occurrence and token; missing or mismatched exits create a gap instead of an
edge. This is observed happens-before, useful for fault-induced retries across
separate request occurrences. It does not prove that the earlier operation's
data was read by the later one; source review remains required for a bug claim.

The graph reader accepts plain JSONL and `.gz` archives, streams large traces
without loading the whole file, and keeps coverage rows as site/sequence pairs.
Call and region child counters live only as long as their parent frame, so a
long original JUnit run does not retain every historical invocation path.

The common runtime deliberately does not infer a shared-field read-from from
method order or equal values. For exact state edges, an adapter must record a
version and its writer under the real synchronization protocol.

The current trace writer assumes one JUnit cluster JVM and one ordered trace
file. Protocol headers carry producer identities across message boundaries,
but a multi-JVM cluster needs per-process trace files and an explicit merge
before this reader can validate cross-process event order. Current pilots use
the existing in-process JUnit mini clusters.

The JUnit weaver and system protocol patches live in sibling modules. A target
exception candidate still needs a matched native FAULT_APPLIED receipt, an
exact target THROW after the fault, and comparison with the unchanged healthy
JUnit. A TARGET_THROW row alone is an observation, not a new-bug verdict.
