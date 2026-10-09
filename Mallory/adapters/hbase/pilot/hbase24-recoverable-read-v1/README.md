# HBASE-24 recoverable ZooKeeper read admission

The exact selected test is `TestZKProcedure#testMultipleMembers`. It starts four
named members (`one`, `two`, `three`, `four`) before starting the coordinator's
procedure. The target is the PB magic prefix check in
`ZKProcedureMemberRpcs.startNewSubprocedure` at source line 205 and the
`IllegalArgumentException` throw at line 210.

The earlier HBASE-24 pilot injected `ConnectionLossException` at the caller's
`ZKUtil.getData` invocation, line 204. That call exits to the `KeeperException`
handler on the affected member; the two fault trials reached the target only on
other members. The [actor audit](../../../../../data/mallory/triage/HBASE-24-5a-actor-audit-v1.json)
therefore blocks promotion of that door.

This selector moves the fault boundary into
`RecoverableZooKeeper.getData(String, Watcher, Stat)` at line 405, on the
underlying `ZooKeeper.getData` invocation. The pinned source catches
`KeeperException.ConnectionLossException`, retries this idempotent read, and
returns the bytes to the caller. In the pinned target class, the call to
`ZKUtil.getData` at bytecode offset 143 stores its result in local slot 5; the
`ProtobufUtil.isPBMagicPrefix` call at offset 150 loads slot 5. This is a
source and bytecode dataflow argument for a retained check in the same
`startNewSubprocedure` region. A retry can change which read result reaches the
check if the znode changes between attempts, although this selected JUnit does
not itself arrange such a data change.

`sites.json` selects only this typed RPC boundary and the unchanged target.
`healthy.json` is calibration only, with `auto.io.doors: false` and one healthy
trial. Its `allow_local_timeline_doors: true` means a future same member,
same region, same thread door before a target check is **temporal evidence**.
It is not an observed graph edge and cannot by itself establish a causal fault
effect or a target exception. The old 5a agent does not emit numeric
`thread_id`, so strict event time graph admission is unavailable with this
runtime pin. The source dataflow claim and runtime temporal claim must be
reported separately.

Run `python3 preflight.py` in this directory to verify the source, JUnit,
compiled call, catch, retry, target dataflow, typed exception, and SHA pins
without starting the workload JVM. The generated [preflight receipt](preflight.json)
passed. [Node1 staging](node1-staging-receipt.json) records the read-only site
and healthy config paths and remote artifact hashes. No HBASE-24 workload JVM
has run from this selector.

After dispatch grants the isolated node1 lane9 healthy slot, run only the
selected calibration and audit with
`MALLORY_HBASE24_NODE1_GRANT=healthy-only /users/ZhenyuLi/.mallory-worktrees/hbase/lane9/runtime/cases/HBASE-24-recoverable-read-v1/run_healthy_node1.sh`
on node1.
The runner checks all remote SHA pins and the lane lock before starting one
trial. Healthy review must verify the exact loaded
class hashes, one named member's line-405 door and later nonthrowing line-205
check within the same `startNewSubprocedure` occurrence and JVM thread, JUnit
success, and an unmodified returned-byte path. A fault pilot needs a fresh
same member after fault check and a strict causal argument; the healthy run
does not authorize a fault or full campaign. An idempotent read retry alone
does not imply malformed PB data or a coordination bug.
