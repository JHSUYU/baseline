# HDFS-21 source and workload review

The selected `BPServiceActor.checkNNVersion` guard compares the software
version returned by the NameNode with the DataNode's configured minimum
NameNode version. A lower version throws `IncorrectVersionException`. In the
released HDFS 3.4.3 source, `retrieveNamespaceInfo` obtains the value through
`bpNamenode.versionRequest()` during the first DataNode handshake. It retries
`IOException` and `SocketTimeoutException` from that RPC, then invokes the
selected check on the returned `NamespaceInfo`.

The mapped original JUnit, `TestDFSInputStream#testSkipWithRemoteBlockReader`,
starts a 1 NameNode + 1 DataNode `MiniDFSCluster` with builder defaults,
writes a 4 MiB file, and tests remote-reader skipping. The released JUnit
passes unchanged (12.854 s). An independent source-probed run also passes
(18.880 s) and reaches the exact selected guard once during startup:
`nnVersion=3.4.3`, `minimumNameNodeVersion=2.1.0-beta`, with the comparison
allowed. The healthy trace records 48 I/O events. The later file reads occur
after this version check and do not exercise the startup guard.

The fault campaign uses observed `versionRequest` RPC responses and durable
startup file flushes before the selected guard. Its exact selector comprises
I/O kind, API, runtime actor/endpoint, ordinal, and exception class. A trial
retains the target only if every ordered selector applies and the same guard
runs after the last fault. An RPC failure that prevents DataNode startup is
recorded as a lost target, not a selected `IncorrectVersionException`.
Coverage feedback comes from production-class JaCoCo method and branch IDs;
the case does not read graph or closure artifacts. The resumable checkpoint,
per-trial plans, traces, coverage, timings, and audit are under
`independent-coverage-io/`; `result.json` records current totals.
`coverage_provenance.py` writes `coverage-provenance.json` with the absolute
node2 path and SHA-256 of each raw JaCoCo execution file, its generation and
parsing commands, and released class/source JAR hashes. Packed coverage TSVs
retain the feedback in Git; the raw JaCoCo binaries stay on node2.

This check is a direct compatibility comparison of one RPC response with a
configuration threshold. Source review gives no evidence of a multi-hop
coordination invariant for this site; that limits its interpretation as an
ad hoc coordination candidate even if fault testing reaches it.

The campaign completed 80 trials in 4430.297 s. All 448 requested fault
events were matched and applied in order, so all 80 trials were strict. The
selected guard ran after the final fault in 79 trials; one trial lost the
target and was excluded from coverage feedback. The maximum exercised
sequence had eight exceptions. Faulted runs added four production method
IDs, 28 branch-unit IDs, and 63 probe IDs over the healthy run. The exact
`IncorrectVersionException` occurred zero times and no new bug was verified.
The last eight trials introduced no production method/branch coverage or
stable I/O family, so the conditional 128-trial extension did not apply.
The per-trial archive and consistency audit passed. The healthy run had five
eligible I/O points before this exact startup guard; the remaining observed
I/O was after the target or outside the selected fault family.
