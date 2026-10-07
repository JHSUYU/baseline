# QJM RPC actor V2: offline repair for HDFS-07/09/10

This independent overlay repairs the old `Client.getRpcResponse` selector in
HDFS-07/09/10. The old probes normalized the RPC thread name by replacing the
dynamic port with `:port` and all digits with `N`. That conflated different
JournalNodes. It cannot establish that an injected response fault and a later
target check concern the same JournalNode.

## Identity chain

1. After `JournalNodeRpcServer.start`, the hook reads the actual listener port
   and `dfs.journalnode.edits.dir` from that server's `JournalNode`, then records
   `NODE_PORT_REGISTER(port, journalnode-N, storageRoot)`.
2. At `Client.getRpcResponse(Call, Connection, ...)`, the hook reads the actual
   `Connection.getRemoteAddress().getPort()`. The probe records
   `RPC_PEER_RESOLVED(port, journalnode-N)` and uses
   that actor as its `sourceKey`. Unknown or ambiguous ports emit
   `RPC_ACTOR_UNBOUND` and **cannot inject**.
3. HDFS-07 already emits `journalNode` from `Journal.storage.getRoot()` at its
   `acceptRecovery` target. HDFS-09 and HDFS-10 now bind the same storage root
   at entry to `checkRequest` and `checkWriteRequest`, and emit `journalNode`
   on `TARGET_CHECK` along with `journalId=test-journal`. `TARGET_THROW` is
   independently actor-bound. `strict_receipt.py` requires ordered applied
   faults, a registered same-thread peer for each RPC fault, and the selected
   same-actor target after the final fault.

The hook is based on the existing HDFS-08 listener-port registration and
connection-port read, with stricter fail-closed handling for unknown actors.
The case-local target and file-I/O hooks are copied into each new overlay;
historical file-only evidence remains separate from the previous coarse RPC
trials. No graph runtime or Docker is used.

## Offline build and evidence

`python3 build_offline.py` creates self-contained case overlays under
`build/HDFS-{07,09,10}/overlay`. It asserts exact bytecode site counts, compiles
against released Hadoop 3.4.3, runs the registry and strict-receipt smoke
checks, and verifies all changed classes with ASM `CheckClassAdapter` on the
full Hadoop classpath. It does **not** launch a cluster or JUnit. The build
uses the original case target/file overlay as input without editing it.

Validation completed on 2026-10-07: all three overlays compiled, registry
smoke passed, and `CheckClassAdapter` reported no errors. Run
`python3 offline_smoke.py` for synthetic calibration, checkpoint, one-trial,
and read-only raw-audit smoke for each case. This smoke creates no JVM.

## Prepared original-JUnit controller

The runtime stage is prepared but has **not** been launched. From this
directory, after the node owner releases a cluster slot:

```sh
python3 run_v2.py --case 07 --name healthy-a
python3 run_v2.py --case 07 --name healthy-b
python3 calibrate_v2.py --case 07
python3 campaign_v2.py --case 07 --init
python3 campaign_v2.py --case 07 --once 1
python3 audit_campaign_v2.py --case 07 --output evidence/HDFS-07/audit-001.json
```

Repeat with `09` and `10` **sequentially**, each with its own two original
JUnit healthy seeds, fresh `campaign-v2/checkpoint.json`, queue, raw trial
directory, and target oracle. `run_v2.py` invokes released Hadoop 3.4.3
`TestQuorumJournalManager` methods with a fresh 3-JournalNode embedded cluster
and case-specific V2 overlay. It uses unique scratch/JVM tmp directories,
dynamic cluster ports, `-Xmx3g`, and a 360-second JUnit timeout. Healthy and
fault trials record JUnit elapsed time, exact method, runtime actor events,
selected fault plan, raw JaCoCo, production method/branch/probe/line feedback,
and SHA-256 hashes. The manifest is written last, after JaCoCo conversion.
Each trial has an immutable `trial-NNNN-attempt-NN` ID.

`calibrate_v2.py` rejects seeds if the original JUnit fails, the three storage
actors or resolved RPC peers are absent, the exact target site/journal is
absent, or raw JaCoCo/feedback hashes are missing. It requires stable actors
and I/O families across two seeds. Historical trials are never imported; the
new effective denominator starts at zero.
The HDFS-07 three-plan pilot raw archive and independent receipt are under
`evidence/HDFS-07/pilot3-raw.tar.gz` and `pilot3-audit.json`. The two original
healthy JUnit seeds for each of HDFS-09/10 are preserved in their separate
`evidence/HDFS-09/healthy-raw.tar.gz` and
`evidence/HDFS-10/healthy-raw.tar.gz` archives. These latter cases have no V2
fault trials yet.

`campaign_v2.py` uses a process lock and atomic checkpoints. It resumes a
selected plan from its complete immutable manifest; an interrupted run without
one retains its raw directory and receives a new attempt ID. It checks
`jvm.pid` before rescheduling, so a surviving JVM cannot overlap its retry.
Place `campaign-v2/PAUSE` to stop at the next JUnit boundary. Before each new
JUnit, the controller requires fewer than five existing Java processes and at
least 8 GiB free disk by default; `--wait-for-resources` keeps the tmux worker
at its checkpoint until these conditions return. The controller
selects observed actor-bound RPC/file I/O preceding the exact target, applies
faults in order, and mutates from newly observed I/O in effective trials. It
prioritizes new production method/branch and I/O-family feedback. A trial is
effective only when every planned fault applies and the selected
`journalnode-N/test-journal` target executes after the final fault. A target
throw remains a candidate, pending source review and clean replay.

The initial budget is 80 effective trials, at most eight faults per sequence,
with a 320-attempt cap. If any of the last eight effective trials adds method,
branch, or I/O-family coverage, the same checkpoint extends to 128 effective,
at most ten faults and a 512-attempt cap. The HDFS-07 pilot was first created
under the former 160/256 caps; `migrate_budget_v2.py` changed only its attempt
cap at the audited 3/3 checkpoint, with before/after SHA receipt, preserving
the three completed trials. Queue exhaustion and attempt cap are
explicit terminal statuses, not 80/128 completion. `audit_campaign_v2.py`
recomputes exact actor/target and coverage/I/O receipts from raw artifacts and
reports checkpoint or SHA mismatches.

## Next runtime gates for each case

Each case requires its own unchanged original embedded-cluster JUnit with a
fresh fixture and a new checkpoint. HDFS-07 uses
`TestQuorumJournalManager#testRecoverAfterIncompleteRecovery`; HDFS-09 and
HDFS-10 each use `TestQuorumJournalManager#testSingleWriter`, but their target
hooks and oracles differ. Run two healthy calibrations per case, checking that
all three JournalNodes register distinct listener ports, that QJM RPC events
resolve to these actor keys, and that the target events carry the corresponding
storage-root actor. Preserve the raw registration, peer, fault, target, JUnit,
and JaCoCo evidence. Then use `strict_receipt.py` per plan and selected actor.
Only a fully applied sequence with the selected target after its final fault
counts as an effective actor-aware trial. A target exception still requires
source review and clean replay before bug classification.

HDFS-09 and HDFS-10 use the same upstream method, but the current overlays
are case-specific. One current JUnit process cannot count as both cases: it
records one target probe/oracle and one immutable plan. A future combined
overlay could share a healthy seed only after separately proving both target
sites and actor gates; fault trial denominators must still be audited per
target. HDFS-07 uses a different upstream method and requires its own runs.

This work is an offline implementation and bytecode validation. No new
actor-aware HDFS-07/09/10 JUnit or fuzz trial has run, so none of their
`actor_identity_recheck_pending` results is complete yet.
