# HDFS-48: archived actor identity recovery

The original, unchanged `TestRenameWithSnapshots#testRenameUndo_1` runs one
MiniDFSCluster NameNode. The historical graph-free campaign selected
`INodeDirectory.replaceChild` for parent `/dir1`, child `foo`, and injected
`Client.getRpcResponse` exceptions. Its coarse thread/ordinal selector was
insufficient to establish the RPC actor for every historical trial.

`audit_heartbeat_actor.py` re-reads the raw manifest, ordered fault events,
JUnit log, and selected guard in every historical target-retaining trial. It
admits only faults whose raw BPServiceActor thread names the same NameNode RPC
port that the JUnit log reports, and whose selected IPC handler runs on that
port after the final fault. The 183 historical attempts contain 128 coarse
target-retaining trials. Exactly 107 meet this stronger endpoint join; 21
remain excluded. All 107 admitted original JUnits passed and none took the
selected `IllegalStateException` arm.

The first 80 admitted trials end at historical attempt 153. Their final eight
(attempts 143–148 and 152–153) add no exact production JaCoCo probe, method,
branch-count bucket, or I/O family. `recompute_actor_coverage.py` independently
replays the original raw `jacoco.exec` files through the archived reporter,
using one disposable temporary directory per trial. The production exact
probe union is 28,773 in the healthy seed and 29,207 at admitted trial 80
(+434). The 107 admitted trials reach 29,229 (+456). Thus the 80-effective,
up-to-eight-fault base budget is met without extension; all admitted plans
actually have one or two faults. The original campaign spent 4,357.590 JUnit
seconds including its healthy seed and all 183 attempts. The point at which
the first 80 admissible trials had run was 3,681.029 JUnit seconds. Archived
extra trials are retained and audited; they do not imply a 128-effective
budget requirement.

The [actor audit](heartbeat-actor-audit.json),
[coverage audit](heartbeat-actor-coverage.json), and
[final result](../result.json) retain raw file SHA-256 receipts and the
historical counters. The selected target never threw, so no new bug is
claimed for this check.
