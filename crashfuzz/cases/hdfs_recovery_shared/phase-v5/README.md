# HDFS-28/29/30 recovery-owner V5 continuation

This directory is an isolated continuation of the unchanged Hadoop 3.4.3
`TestBlockRecovery2#testRecoveryTimeout` embedded-cluster JUnit. It does not
alter `phase-v4/`, its 128 completed attempts, or any case result/checklist.
No V5 cluster JUnit has run yet.

## Archived boundary and new queue

`migrate_v4.py` verified the immutable V4 state SHA-256
`c990b52036d45f25a4370c611a2254fa3bdd580853a392226909ad04dd3a2b1b`
and stored pointers to all 128 archived receipts. The imported counts are
HDFS-28 **18**, HDFS-29 **39**, HDFS-30 **39** strict ordered injections with
a same-recovery-owner target after the final fault. They are historical,
not V5 trials. New trial numbering starts at **129**; V5 has completed zero.

The 789 pending V4 IDs remain distinct and unchanged. Phase-independent
prefix joining to the *strict parent's raw trace* identifies 196 pairs whose
second fault precedes HDFS-29/30 on the same owner. Those pairs get three
selection turns out of four; the fourth retains exploration of the other
593 plans and fault-induced retry behavior. Each candidate is rechecked
against its **own** new runtime trace before it earns effective credit.
Previously strictly injected IDs cannot be selected again. The 21 pending
IDs with earlier unmatched attempts retain bounded retries; prior attempts
remain in the archive.

## Identity and oracle

The V5 overlay keeps V4's six selector columns and file phase unchanged,
then adds a mandatory cluster startup episode column. V5 raw events include
the registered coordinator DataNode, BP ID, block ID, recovery ID, recovery
attempt root, and an execution-local command token. The token is attached
to the `RecoveringBlock` received in `BPOfferService` and follows that same
object into `RecoveryTaskContiguous.recover`; a repeated command receives a
different token. An unregistered DN, ambiguous server-side recovery owner,
or any missing/different identity dimension fails closed. The raw NN socket
endpoint remains evidence but is not treated as a stable selector across
ephemeral-port JUnit runs.

HDFS-28 has a separate producer lane at active-NN recovery command receive,
before the first target check. It stays disabled unless **both** new healthy
original JUnits show a stable, bound command event before that check. If the
test uses a direct recovery path or the join is ambiguous, HDFS-28 remains
`budget_recheck_pending` at its historical 18/128 instead of consuming
attempts from the HDFS-29/30 lane. A target exception is a candidate for
exact-plan replay and source review, not an automatic new-bug verdict.

## Gate and checkpoint

Offline checks have already passed: `python3 offline_smoke.py` (ASM weaving,
`-Xverify:all` class loading, all core JSON event types, synthetic token and
wrong-owner exclusion) and `python3 audit_v5.py` (independent V4 raw queue
and receipt audit). Their machine receipts are `offline-smoke.json` and
`offline-audit.json`. `campaign-state.json` currently has `active=null`,
`v5_attempts=0`, and `awaiting_two_healthy_calibrations`.

After a separate cluster-JVM slot is assigned, run two **sequential** healthy
seeds in independent scratch directories:

```sh
python3 run_original.py --instrument --output healthy-v5-a --timeout 420
python3 run_original.py --instrument --output healthy-v5-b --timeout 420
python3 audit_calibration.py
```

Only if `calibration-gate.json` says `passed=true` may `campaign.py --once 1`
run a first V5 fault plan. Inspect its raw trace and independent
`audit_v5.py` result before lifting the one-trial gate. Each trial gets a
fresh `runs/trial-NNN/` scratch, fault TSV, original JUnit manifest, raw
trace, and JaCoCo files. The controller stores `active` before launch; a
launched trial without a final manifest stops for manual reconciliation
instead of silently rerunning. An existing complete manifest is assessed
without launching JUnit again. `pause.request` stops at the next complete
trial boundary.

Each active case counts one shared JUnit as one attempt. Its base goal is 80
effective plans with at most eight faults and **320 total attempts including
V4's 128**. Only a last-eight-effective coverage or I/O gain at 80 enables
the 128-effective/max-ten-fault extension with **512 total attempts**. At a
cap with an unmet goal, status is `budget_recheck_pending`; the next step is
to revise target-preceding I/O or the original JUnit scope, not reuse old
plans. The 420-second per-JUnit limit is a safety bound, not an effective
trial. Reserve at least 1 GiB free scratch space; the 128 V4 run directories
occupy about 46 MiB, and V5 may append up to 384 new attempts per active
case under its conditional cap.

See [SOURCE_AUDIT.md](SOURCE_AUDIT.md) for the exact source and bytecode hook
review. Do not combine V4 and V5 production coverage sets until the two new
healthy traces confirm compatible probe identities; V5 stores a fresh union
and keeps V4's union only as ancestry.
