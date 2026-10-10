# HDFS-48 heartbeat response healthy admission on node2

This immutable sibling repairs the node2 portability of
`hdfs48-heartbeat-response-v1`. The original v1 package and its provenance
remain unchanged. The original Hadoop 3.4.3 JUnit is
`TestRenameWithSnapshots#testRenameUndo_1`; the selected target is the
`INodeDirectory.replaceChild` identity check at line 356 on
`hdfs-cluster-1/nn0`. The typed candidate is the `Client.call` response
operation at line 1529, where an `IOException` can be raised before the RPC
response is consumed by a named `BPServiceActor` heartbeat caller.

Node2 lacks the old `/users/ZhenyuLi/.mallory-worktrees/hdfs` checkout. Its
existing `hdfs-identity-v8` tree has the same complete source digest and
matching source and compiled class hashes for all eight original provenance
pins. Its `.git` metadata is incomplete, so this package checks the full
source digest and exact file hashes there. `original-provenance.json` is a
byte-for-byte copy of v1's pinned provenance; `node2-provenance.json` maps
only the source/class paths to the equivalent tree and the small adapter and
evidence paths to local SHA-identical copies. No duplicate worktree is made.

The healthy configuration permits one fault-free JUnit and no automatic
promotion. Runtime admission still requires JUnit 1/0/0, a direct setup
check on `hdfs-client`, the nonthrowing selected occurrence on nn0 after
rename, and an observed pretarget typed response door on a named DataNode
heartbeat actor. Endpoint joining and any event-time causal path must be
audited from the new trace. The older 107 CrashFuzz heartbeat faults retained
the target but do not prove a Mallory graph path.

Run `python3 preflight.py --static` on node0 or node2 to verify both
provenance records, package hashes, source digest, compiled classes, frozen
core, agent, adapter, archived evidence, selector, target and typed door
without Java. A normal `python3 preflight.py` on node2 also checks for an
unused output directory and free space; it still starts no JVM. After a
separate dispatch GO, `MALLORY_DISPATCH_ADMITTED=1 ./run_healthy.sh` holds the
shared node2 HDFS lock and launches the single healthy calibration.
