# Optional HDFS-28 file I/O successor

`ipc_successor_v3.py` naturally stopped at 214 original-JUnit attempts and
41 effective same-owner, postfault HDFS-28 checks. Its independent full raw
audit has zero errors and no selected target exception. This alternate
`TestPipelinesFailover#testLeaseRecoveryAfterFailover` ledger is separate
from the shared HA JUnit ledger.

`file_successor_v4.py --preview` reads both healthy traces and every exact,
effective original-JUnit trace. It accepts a `checkReplicaFiles` file I/O
event only if the existing runtime identity verifier binds its physical
DataNode and recovery root, and a later HDFS-28 guard on that same owner/root
appears in the raw trace. It generates only singleton `IOException` and
`FileNotFoundException` selectors not present in the old `seen` ledger.
The frozen preview found **72 unique new IDs**: 24 local to the recovery
owner and 48 on a remote replica bound to that owner. Each of the four
`FsDatasetImpl.checkReplicaFiles` sites contributes 18 plans. The full
selector, source trace SHA, event sequence, physical owner, root, and
local/remote distinction are in `file-v4-preview.json`.

This is an **offline contingency**, not an active campaign. The shared HA
RPC successor has priority for the conditional 128-effective aggregate
target. If that successor's exact/effective yield is insufficient, V4 can
start from the alternate JUnit's natural queue-exhausted boundary after a
fresh independent raw audit. Its handoff preserves every completed row,
old queue/seen prefix, coverage and I/O union, and active plan; it appends
the 72 new IDs, raises the attempt cap to 512, and records old/new SHA in
an atomic intent and receipt. It retains the alternate campaign's own
80-effective goal and max-eight-fault sequence setting. Selection prefers
local file plans before remote plans; whenever RPC descendants are
available, four of five choices prefer RPC, leaving a file exploration
slot. The node1 shared JVM start lock, Java and 10 GiB disk gates remain
in force. No historical trial or pilot plan is repeated.

Offline checks: Python compilation passed; two independent previews gave
the same SHA-256 `503e3ab44684bed74a7207b7f8e0f67d75195b887105c7bcf33a3a11de5b9a43`.
A dry-run migration preserved the old completed/queue/seen prefixes and
coverage/I/O state, with 72 noncolliding IDs. Source SHA-256 is
`d45c88f9473ac19b28191c175f664a03f5c6a78124e3d412892bb023716ab61a`.
No JVM was started by these checks.
