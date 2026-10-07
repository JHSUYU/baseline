# HDFS-16 sender-aware RPC overlay

The unchanged Hadoop 3.4.3 test is
`TestClientProtocolForPipelineRecovery#testUpdatePipeLineAfterDNReg`. It runs
one NameNode and two DataNodes. At upstream test lines 778–787, the `main`
thread takes DataNode 0's `DatanodeRegistration` and manually calls
`DatanodeProtocolClientSideTranslatorPB.registerDatanode`; BP worker threads
can call the same translator method. A thread name or the old global API
ordinal cannot distinguish their senders.

## Repair

`build_offline.py` reads the released
`hadoop-hdfs-3.4.3-sources.jar` translator (original SHA-256
`07f1cc59498881a424ec2e6c5837a6299d73dc93417cd1e4da327d172d2f0f98`)
and generates an isolated source overlay. Six synchronous
`DatanodeProtocolClientSideTranslatorPB` methods with an explicit
`DatanodeRegistration` bind `dn:<DatanodeUuid>|bp:<blockPoolId>` only around
their actual `ipc(...)` call and restore the prior binding in `finally`.
The manual `main` call is therefore identified from its argument, as are
background BP calls. The translator constructor records the configured NN
port. The `Client.getRpcResponse` hook passes its actual connection remote
port to the probe. A DN RPC is injectible only when its thread has a complete
UUID/BP binding and the remote port was registered by that translator.
Unbound, incomplete, or unrelated client RPCs are recorded as unbound and
cannot match a DN plan.

The new selector is `(marker, API, senderActor, actor-local ordinal,
exception)` in a five-column TSV. The old four-column plans are rejected.
`BlockInfo.setGenerationStampAndVerifyReplicas` keeps the original exact guard
hook: `TARGET_GUARD` records block ID, caller, current/proposed generation
stamp, and guard outcome; `TARGET_EXCEPTION` keeps the same context.
`strict_receipt.py` requires each ordered fault to have an active same-thread
DN binding, a registered NN port, and the selected block/caller/proposed-stamp
guard **after the last fault**. A target exception remains a candidate until
source review and a clean same-plan replay.

The source-derived overlay, including the preexisting target and edit-log
hooks, is built at `build/overlay`; it never edits the historical case
campaign or its files. Run `python3 build_offline.py` to compile against the
released Hadoop jars, verify `Client`/translator/probe bytecode with ASM,
assert the six bind sites and one NN endpoint registration, and run a no-cluster
sender/peer/target smoke. The build receipt and generated source remain in
ignored `build/` for inspection. The last offline build passed on 2026-10-07.

## Historical evidence and runtime plan

The prior 80-trial checkpoint at
`cases/HDFS-16/independent-coverage-io/campaign/checkpoint.json` contains
40 strict postfault target-retaining trials. Of these, **22** include an
unidentified `registerDatanode` sender and must be rerun with the V2 actor
selector: trials 22, 23, 26–29, 33–34, 36, 38, 45–50, 63–64, 68, 71, 73–74.
The other **18** comprise 12 client→sole-NN RPC-only trials and six mixed
client-RPC/edit-log trials. Their original traces, source check, JUnit and
coverage are retained as *historical non-DN evidence* for separate review;
they do not become actor-aware V2 effective trials automatically. No purely
file-only trial is among the 40 effective historical trials. Prior JaCoCo
coverage and elapsed times remain valid observations but cannot fill the V2
DN identity gap.

After node1 is explicitly released, run two fresh original JUnit healthy
calibrations in separate scratch directories with this overlay. Require two
distinct DN UUID/BP actors, the manually issued `main` registration to carry
DataNode 0's UUID, a registered actual NN peer port for every selected DN RPC,
and the expected block/caller/proposed-stamp target contexts. Then start a
new resumable actor-aware campaign/checkpoint; seed only observed V2
selectors, preserve per-trial raw trace/plan/JaCoCo/JUnit/time, and apply
`strict_receipt.py` before counting an effective trial. Keep historical
client/file evidence and old 80-round totals in their existing archive.

No HDFS cluster JUnit or new fuzz trial was run for this repair. HDFS-16
remains `actor_identity_recheck_pending` until its own runtime calibration
and new actor-aware trials are complete.
