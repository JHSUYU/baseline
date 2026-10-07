# HDFS-39 sender-aware RPC overlay (offline preparation)

Scope: Hadoop 3.4.3 original `TestFileAppend#testMultipleAppends`, one NameNode
and four DataNodes, target `FSDirAppendOp.appendFile:131` on
`/testMultipleAppend/foo`. This directory is independent of the historical
HDFS-39 campaign. No cluster JUnit has been run with this V2 overlay yet; the
case result and 104-check table retain their pending status.

## Why the historical count cannot be promoted

The saved old `campaign/checkpoint.json` has SHA-256
`d0b03a25e1a1a0d0b4d279abedd5a14c77adf95dc6821424a10757fbe28de3c7`.
It records 205 attempts and 128 trials with all ordered faults applied and the
same path/block guard after the last fault. Of those 128, **109 plans contain
`DatanodeProtocolClientSideTranslatorPB.blockReceivedAndDeleted`** but the old
`Probe.io` reported endpoint `nn0` with no sending DN. These plans require
sender-aware reruns. The other 19 are 15 client RPC and four edit-log-flush
plans (trials 01–10, 12, 116, 118, 121, 124, 125, 128, 130, 134). They remain
valuable historical source/coverage evidence; the four file-only plans do
not have a DN sender ambiguity. None is silently counted in a new V2
effective denominator because the original RPC peer was not recorded and
the new run uses a different selector schema.

## Source binding and failure gate

`build_offline.py` reads released Hadoop 3.4.3 translator source JARs and
patches generated copies. It adds only a read-only registration hook to the
existing JUnit's four-DN fixture; its workload operations and assertions are
unchanged. The `DatanodeProtocolClientSideTranslatorPB` hook binds the actual
`DatanodeRegistration` UUID and block-pool ID, plus **all** block IDs in the
`blockReceivedAndDeleted` batch, around the synchronous IPC call. The client
append translator binds the exact source path. Both use `try/finally` so a
fault cannot leak context to a later RPC. `Client` gets the real connection's
remote port for send and response-wait probes. `Probe` maps the four fixture
UUIDs to role-relative `dn0..dn3` and registers the actual NameNode port and
block pool. A DN fault selector is `(marker, API including sorted block IDs,
nn0<-dnN, role-relative ordinal, exception)`. Raw events retain UUID, block
pool and peer port. Unknown UUID, missing/mismatched block pool, unknown peer
port, empty/invalid block batch and wrong append path are fail-closed: they
cannot be selected or injected. The existing file flush remains `nnlocal`.

`strict_receipt.py` requires every planned fault in order, an exact registered
NameNode peer, same-thread DN UUID/block-pool/role for each DN RPC fault, and
the healthy target block among each faulted block-report batch. It then
requires `FSDirAppendOp.appendFile:131` on the same path and block **after
the final fault**. It reports `COMMITTED` branch and exact target exception
counts separately. An exception is an observation, not a new bug: the
original healthy JUnit itself sees the transient `COMMITTED` exception and
recovers via `DFSClient.callAppend` retry. Any failed JUnit plus exact target
exception needs source review and clean same-plan replay.

## Validated offline

Run `python3 build_offline.py` from this directory or by absolute path. It
compiles the generated original-class overlay and original JUnit wrapper,
checks each required bytecode hook with `javap`, checks the six changed
classes using ASM `CheckClassAdapter`, compiles the JaCoCo converter, and
runs no-cluster role/peer/context/target and strict-receipt smokes. The
generated classes, source and `offline-receipt.json` live in ignored `build/`.
The V2 converter analyzes the three changed HDFS production classes from
the overlay so their JaCoCo IDs are not lost to a release-JAR mismatch.
`python3 -m py_compile` passes for the five Python tools. This validates
linkage, not runtime role registration in the embedded cluster.

## Safe runtime continuation after a cluster slot is released

1. Copy this independent directory and its case-local dependencies to the
   reserved host if needed. Run `build_offline.py` there and record source,
   overlay and release-JAR hashes. The original `OriginalHdfs39Test` wrapper
   is compiled into the new overlay; no old probe classpath is used.
2. Run **two new** fault-free originals sequentially using
   `python3 run_original_v2.py --name healthy-a` and `--name healthy-b`.
   Convert each JaCoCo exec with
   `python3 coverage_v2.py --name healthy-a` (and `healthy-b`). These commands
   are prepared but have **not** been invoked in this offline task.
   Then run `python3 calibrate_v2.py`: it writes an immutable calibration
   receipt only if both originals pass and agree on the exact block and at
   least one stable same-block DN I/O family.
3. Require both JUnits to pass; four unique UUID→role mappings, actual
   NameNode port and block-pool binding, DN block-report send/response events,
   and the exact target path/block guard must appear in each trace. Build a
   fresh queue only from observed role-aware I/O before the target, use
   JaCoCo production method/branch/probe and new I/O family feedback, and
   store queue/current/completed atomically in a **new** V2 checkpoint.
   Selectors from the old `nn0` campaign must not be imported verbatim.
4. Execute one plan per immutable run ID (`trial-0001`, etc.) with
   `run_original_v2.py --name trial-0001 --plan <absolute-plan.tsv>`, then
   `coverage_v2.py --name trial-0001`, followed by
   `strict_receipt.py --trace <trace> --plan <plan> --target-context <context.json>`.
   The context JSON is derived from the healthy target guard and has keys
   `path` and `block_id`. Record JUnit time, all fault matches, exact role and
   peer, post-final target, and production coverage. Do not retry an existing
   immutable run ID; resume from the next uncompleted plan after auditing its
   manifest. Unmatched and target-lost attempts stay in the ledger but do not
   consume the effective budget.
5. Use the case budget of 80 effective trials, up to eight ordered faults;
   if the last eight effective trials add production branch/method coverage
   or a stable I/O family, extend to 128 effective and ten faults. Any
   target-exception candidate needs a clean same-plan replay and source
   classification. Preserve the 205 old attempts as a separate legacy stratum.

The V2 runtime queue/controller still needs to be wired to the new immutable
runner after the two healthy calibrations. This directory does not claim a
completed V2 trial or restore `quality_complete` without that work.
