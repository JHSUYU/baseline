# SOLR-40 exact reference handoff stage

The node0 v1 healthy run is sealed at
`data/mallory/calibration_solr40_watcher_handoff_v1_node0/SOLR-40`.
Its unchanged four-node `TimeRoutedAliasUpdateProcessorTest#test` passed
one JUnit, reached eleven named exact `getAliasProps@132` checks, and observed
36 named typed `AliasesManager.process@2312` watcher doors. The committed
campaign reported zero eligible doors because the watcher callback and
request have different occurrences and threads. No full fault run is admitted.

`audit_v1.py` adds only balanced same-thread child-return edges to the
read-only graph. It finds 18 event-time watcher-to-target **candidate** paths
and zero observed paths. One witness is door 5000, nested `setIfNewer` write
5016, `getAliases` read 5887, child exit 5888, exact target check 5889.
The shared-state edge is candidate because the old Probe samples a field
version after the actual bytecode access. A different watcher door can share
an object/version sample without belonging to the write's task; same-node
time order alone is insufficient.

The isolated `exact-reference-field.patch` changes generic object-reference
field instrumentation to record the actual value reference from the
`GETFIELD`/`GETSTATIC` result or `PUTFIELD`/`PUTSTATIC` operand. The graph
still requires a unique producer for the owner, field key, and value identity.
Primitive and null values retain sampled status. `call_return.py` adds a
general child-return bridge only when the entire actor/thread region stack is
balanced, IDs and sequence numbers are unique, and the child exits to a
still-live parent. `gate_v2.py` admits only an observed event-time path that
contains the exact alias field write and read, exact reference identity, and
the child-return edge. Sampled state stays candidate and cannot promote a
healthy seed.

The v2 release is **source-staged and unbuilt**. `config.staged.json` is
healthy-only (`calibration_only=true`, one trial, no auto-promotion) and
contains `PENDING_ISOLATED_RELEASE` placeholders. It must not be launched.
`admission-request.json` has `go=false`; no JVM was started for this stage.
Run `python3 preflight_stage.py` for a read-only source, patch, evidence,
and offline-test check. The v1 output is never edited.

To proceed, build the patched agent in an isolated work directory, pin its
SHA and bytecode into a finalized v2 config, and run exactly one fresh
healthy JUnit on node0 with the existing disk, RAM, source, and lane locks.
The fresh result must pass the JUnit, reach the exact nonthrowing target on a
named physical actor, observe the typed watcher door before it, and provide
an observed door → alias write → exact alias read → target path in one
actor/epoch. A separate review is required before any full fault campaign;
the current request does not authorize one automatically.
