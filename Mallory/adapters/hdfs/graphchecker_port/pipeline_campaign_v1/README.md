# HDFS-11 unchanged-JUnit GraphChecker campaign, staging v1

This stages a **new** GraphChecker-native campaign for the original Hadoop
3.4.3 `TestEncryptedTransfer#testLongLivedClientPipelineRecovery[0]`. No
fault site or exception site is hand-listed. The target check and throw come
from the reviewed HDFS-11 inventory; Soot and the original GraphChecker seed
choose the I/O doors, regions, value edges, and coverage sites. The campaign
request is `campaign-request-v1.json`; `scope-input-v1.json` pins the exact
ordered classpath and asks for `original_graphchecker_seed`,
`original_typed_io_frontier`, and static value projection.

The source check is `BlockTokenSecretManager.retrieveDataEncryptionKey` at
`BlockTokenSecretManager.java:552`; the `InvalidEncryptionKeyException` throw
is line 555. The expected Soot sites are `#u8` and `#u20`, but
`materialize_config.py` accepts only the unique sites **in a fresh** weave
manifest. The original JUnit uses four DataNodes, expires a data encryption
key, stops one pipeline node, and verifies the client clears its key once.
Historical fault-free diagnostic trace
`.study-repairs/diagnostics/hdfs11-postcall-key-campaign/results/HDFS-11/healthy-postcall-key-v1/runtime_trace.jsonl`
has one exact line-555 throw at sequence 936. That diagnostic used a different
runtime and does **not** supply the new campaign's structural fingerprint.

## Required preparation, after an execution slot opens

1. On the assigned host, build or pin the current static planner, original
   GraphChecker seed, weaver, and runtime from the version containing commit
   `70d232d6939d57ca2d77bcf1ca52592cda85c153`. The runtime jar must
   contain `TargetThrowFingerprint.class`; the currently staged old runtime
   jar lacks it. Verify source and compiled target hashes against the request.
2. Recreate the HDFS merged class tree at
   `/dev/shm/mallory-hdfs11-pipeline-classes-v1` with
   `prepare_static_classes.sh` and the system-wide HDFS protocol overlay using
   `MALLORY_HDFS_COMMON_SCOPE=ipc`. Recreate the pinned overlay classpath
   directory on the assigned host. The scope input's ordered classpath must
   exist exactly as written; if the host paths differ, version a new request.
3. Run the current `ScopePlanner` with a host-local copy of the pinned scope
   input, writing its output and `original_engine_output_dir` to isolated
   local storage. The ordered classpath must place the planner's ASM 9.4
   dependencies before Hadoop's ASM 5 dependencies. The
   output must contain one check at line 552, one typed throw at line 555,
   `STATIC_VALUE_EDGE` rows, and general Hadoop IPC `IOException` doors.
   `materialize_config.py` checks those conditions and writes the immutable
   campaign config. Pass it the exact weaver and runtime jars present in the
   scope input's dependency classpath, plus the current analyzer jar. The
   original GraphChecker seed map (`graphchecker_static_scope_map.jsonl`) is
   the sole trace-analysis digest authority. The merged Soot MAY map
   (`static_scope_map.jsonl`) is a separate SHA-pinned sidecar used to rank
   observed fault doors; it adds no causal graph edges.
4. Run **two fresh independent no-fault** `Mallory.core.graphchecker_campaign`
   trials using `JUnitTrialMain` and parameter index 0. Require one JUnit
   execution per trial, healthy pass, target reach, and a stable typed
   line-555 `TARGET_THROW` structural fingerprint/count. The expected throw
   is the healthy envelope and earns no detection credit. The old trace
   cannot replace either fresh run.
5. Only then start `Mallory.core.graphchecker_fuzzer` with one independent
   trace passed as `--additional-healthy-seed-trace`; its archive hash is
   checkpointed along with the fuzzer's own healthy run. Scheduler v5 admits
   up to 192 fault trials / 4 hours,
   six faults per plan; its first 128 bootstrap trials are capped at three
   faults. A plan is eligible only if its exact `FAULT_DOOR` is observed, its
   `FAULT_APPLIED` receipt matches, and the target remains reachable.

The first **nonterminal** wave stops at a cumulative 64 fault trials:

```bash
python3 -m Mallory.core.graphchecker_fuzzer \
  --config /LOCAL/HDFS-11-PIPELINE-GC-V1/config.json \
  --out /LOCAL/HDFS-11-PIPELINE-GC-V1/campaign \
  --stop-after-fault-trials 64
```

The stdout status `paused_wave` means the checkpoint is still `running`,
`terminal=false`, and retains the queue and full immutable 192/4h/max6
budget. After checking the host again, resume with the **same config bytes
and campaign directory** and the same pinned independent healthy trace,
first `--stop-after-fault-trials 128`, then without that option for the final
full budget. The scheduler refuses a changed config hash, budget, or healthy
seed archive. If the queue exhausts, the time budget expires, or the
target is lost before 64 trials, record the actual terminal status instead
of marking a completed 64-trial wave. A comparable 64-trial local footprint
is about 3.0 GB including static/healthy files and one transient raw trace;
admit it only if fresh tmpfs, root, memory, and process checks leave the
case-specific local reserve.

An extra exact target throw after a strictly applied generic RPC fault, with
the throw in that fault's causal closure and its structural profile exceeding
the healthy envelope, is a **detected target candidate even if a caller
catches and retries**. Separately classify the call path from the throw's
`stackMethods`, sender-side SASL trace, RPC identity, and source:
`DataXceiver.writeBlock` (HDFS-17967), `DataNode.DataTransfer.run`
(HDFS-17899), or the JUnit's expected `DataStreamer` client retry. A claim
that a particular PR's *missing retry* defect occurred needs the matching
caller and failure to refresh the key; an extra common target throw alone
does not establish that claim.

`pg0-bounded-local-resource-policy-assessment-10g9g-v2.json` is an assessment,
not a launch receipt. Each launch needs fresh PG0, local root, tmpfs, memory,
and process-isolation preflight. Keep raw traces and trial scratch local.
Enforce PG0 start available ≥10 GiB, stop ≤9 GiB, at most two concurrent
bounded campaigns, ≤32 MiB PG0 durable allocation for this campaign and
≤64 MiB aggregate, with checks before each trial and durable write and a
poll interval ≤3 seconds. The generic `capacity_guard` config checks PG0,
root, tmpfs, memory, private local tree, and dedicated durable allocation
before preparation and each trial. On refusal it writes `capacity_pause`
with the exact reason to the nonterminal checkpoint; resume uses the same
config and campaign directory after a fresh admission check. A monitored
process group handles changes during a running JVM. No HDFS trial has been
started by this staging.

Read-only sizing on node1 at staging time found 5.20 GB free in `/dev/shm`
and 1.70 GB free on root. A comparable HDFS48 static plus healthy tree used
1.90 GB; a comparable HDFS32 GraphChecker campaign used 538.5 MB for 48
trials, with a 346 MB uncompressed raw-trace example. Extrapolating 192
trials, the new class tree, and one transient raw trace gives about 4.4 GB
of tmpfs use. With a 1 GiB local reserve the full budget needs at least
about 5.5 GB free *before* admission; node1's measured 5.20 GB does not
pass that estimate. The 1.90 GB HDFS48 tree is pinned evidence and must be
preserved. The 64-trial first wave pauses without changing the full budget,
then can resume after old raw data has been bounded and the host passes a
fresh guard.
