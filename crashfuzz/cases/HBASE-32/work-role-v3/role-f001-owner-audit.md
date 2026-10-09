# HBASE-32 V3 role-f001: source and raw evidence audit

Classification: **strict, same-actor recovery-wait candidate; new bug unconfirmed**.
This is the V3 dynamic meta-host/secondary-replica plan, not an s272 exact-plan
replay and not a main or supplemental fuzz-effective trial. The unchanged
`TestRegionReplicaFailover#testLotsOfRegionReplicas` returned no JUnit result
within its 600 s cap; the bounded runner exited 124 after 641.95 s including
shutdown. The injected `DoNotRetryIOException` at B7 is the expected target
exception. The candidate concerns subsequent recovery progress.

## Exact actor and fault receipts

The successful pre-fault meta OPEN is RS39265 (`role-f001.log:1267`). F1 is a
`MASTER_OPENED_RPC` DNR on that physical server, table2 replica 8, with the
recorded raw primary and secondary region (`:5473`). F2 is the selected first
`FlushRegionCallable.call:81` RPC DNR on the **same** raw primary, raw secondary,
stable region, and numeric replica 8 (`:7240`). B7 rethrows once afterward
(`:7267`). The original HBase log shows only this RS aborting before the test
shutdown (`:7333`), so the 3-RS fixture was not exhausted by simultaneous
fault-driven aborts. The create-table workload has only 60 successful table2
child region assignments before shutdown, compared with 600 in passing
healthy/replays. `role-f001.receipt.json` independently records strict plan,
two applied faults, same-actor B7=1, `identity_valid=true`, JUnit incomplete.

## Wait chain and recovery timing

Trace-only lock hook records RPC handler thread 315 READ ACQUIRED at
`role-f001.log:8388`, event 329, `ServerStateNode` identity `9f2b32a` for
RS39265. `RegionServerTracker-0` begins WRITE on **the same node and server**
at `:8600`, event 330, after expiration begins at `:8599`. No matching READ
RELEASED or WRITE ACQUIRED occurs before the first shutdown hook at `:35104`
(13:39:29 UTC). `audit_lock_trace.py` reports zero malformed release events
and an active reader at this WRITE attempt. After shutdown, READ releases
at `:43384`, WRITE acquires at `:43385`, then the **first** meta-host SCP is
scheduled at `:43449` (13:39:54, `carryingMeta=true`). This order distinguishes
the stalled recovery from ordinary lengthy post-SCP assignment.

All five `Thread.print -l` snapshots at 130, 200, 300, 500, and 607 s retain
the same edges: tracker waits in `AssignmentManager.submitServerCrash:1980`
on RW AQS `0x00000007bc1980e0`; handler 315 waits in
`AssignmentManager.updateRegionTransition:1298 → RegionStateNode.lock:337`
on region AQS `0x00000007bd8ddb68`; PEWorker-6 owns that region AQS and is in
`RegionRemoteProcedureBase.execute:323 → AssignmentManager.persistToMeta:2290
→ RegionStateStore.updateRegionLocation:238 → HTable.put:565`. Pre-shutdown
log entries retry writes to the aborted meta RS39265 (`:8724` onward). In
HBase 2.6.6 source commit `d5f63f523c`, `AssignmentManager:1256–1278`
retains the server READ lock across transition handling, while `:1980–2008`
requires WRITE before scheduling SCP. `RegionRemoteProcedureBase:289–323`
holds the region lock while persisting to meta. The observed dependency is
therefore tracker WRITE → handler READ → PEWorker region lock → meta write
retry → unscheduled meta-host SCP.

This is strong evidence of a long-lived recovery wait under the selected
schedule; it does **not** establish an infinite Java deadlock. The same broad
mechanism appeared in the independently reviewed s272 original run, but six
exact s272 replays passed, including two meta-host controls with no active
READ holder at tracker WRITE. V3 role-f001 is an independently selected
role-aware plan and reinforces the mechanism, not deterministic triggering.
The earlier HBASE-21508 fix introduced current read/write fencing; HBASE-24526
involved meta assignment after its SCP had already started. These contrasts
do not by themselves establish novelty. Keep `new_bug=false` until bounded
V3 same-selector replay and independent source/known-issue review complete.

## Integrity and next gate

`role-f001.receipt.json` raw log SHA-256 is
`5712819ef82281c1ab39b6d42f47661c8b1a9aa2eb96ca90cc201c1b85b6db4e`;
JaCoCo SHA-256 is
`6cf4e65ffecf57a7eed47ebbfe679940823c62cf8029926965a9ada9962f0385`.
The 18-file remote archive on node1 has archive SHA-256
`ba9099d78fc3f34e178ce7197b05ececea5f36a06817410fbc9bc60a8c0f3ac6`
and manifest SHA-256
`c8734b11b0091a51e647583a159c593c265486a585aa71174bf425a0cac8514f`;
every member was rehashed remotely. The next bounded V3 run must use the same
frozen selector/agent/JAR/JUnit hashes and record meta-host identity, raw
region actor, B7, SCP timing, lock identity, complete JUnit result, and dumps.
