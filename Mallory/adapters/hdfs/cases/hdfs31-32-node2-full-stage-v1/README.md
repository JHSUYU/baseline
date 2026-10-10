# HDFS-31 and HDFS-32 full Mallory campaigns (offline stage)

This package stages two original Hadoop 3.4.3 `MiniDFSCluster` JUnit methods
for node2. It does not contain a new workload and was prepared without
starting a JVM. The original test and target `DataNode` class bytes are
SHA-pinned. The frozen `fa5f3bde` Mallory core, `38658059` agent, and
`9d828a42` HDFS adapter are pinned by `manifest.json` and `preflight.py`.

| Case | Original JUnit | Exact target | Selected I/O |
| --- | --- | --- | --- |
| HDFS-31 | `TestDiskError#testDataTransferWhenBytesPerChecksumIsZero` | `DataNode.getBPOSForBlock`, guard 1833, selected `IOException` 1835 | DataNode heartbeat RPC; original test's metadata `RandomAccessFile.writeByte`/`writeInt`; observed automatic IPC and file doors |
| HDFS-32 | `TestDeleteBlockPool#testDfsAdminDeleteBlockPool` | `DataNode.deleteBlockPool`, guard 3819, selected running-pool `IOException` 3822 | DataNode heartbeat RPC; `DFSAdmin.deleteBlockPool` client RPC; observed automatic IPC and file doors |

Each independent output has 80 fault trials or 3600 seconds, whichever
comes first, at most three exception faults per sequence. HDFS-31 has a
240-second trial timeout and HDFS-32 a 360-second timeout. A normal
`budget_exhausted` or `queue_exhausted` result completes the configured
campaign. Graph-path quality and faulted target retention are recorded as
outcomes; neither is a second completion test. `collect_terminal.py` checks
the checkpoint and per-trial count without starting Java.

The archived Mallory calibrations for both cases failed before the selected
operation because their old Java agent caused a duplicate-class
`LinkageError`. They are negative setup evidence, not valid healthy seeds.
The new node2 campaigns use a later immutable agent and start in fresh
output directories. The prior source review
`hdfs31-32-current-fault-model-source-review-v1.json` observes that none of
the selected I/O exceptions has yet been shown to change either map-lookup
predicate. This limits bug expectations, but does not exclude the sites from
the requested full baseline budget.

HDFS-31's original method calls `dn0.transferBlock` with the existing
`ExtendedBlock`, so the selected guard is expected on dn0 after file setup.
The test compares a `DataNode` object to a UUID string while selecting the
other DataNode; the actual target actor and block-pool ID must be read from
the new trace. HDFS-32 uses the federated DFSAdmin method because the other
original `testDeleteBlockPool` intentionally catches the selected exception
without faults. The DFSAdmin method sends a no-force request followed by a
force request for nameservice 2's block pool. The exact target site and
DataNode actor are pinned, while the RPC request's force flag remains a
runtime identity question. A target exception cannot become a bug claim
until the specific request and original JUnit expectation are checked.

On node0, `python3 preflight.py --case HDFS-31 --static` and the analogous
HDFS-32 command inspect a byte-identical source mirror and all pinned files
without Java. On node2, dispatch sets `MALLORY_DISPATCH_ADMITTED=1` and runs
`./run_full.sh HDFS-31` or `./run_full.sh HDFS-32`. A shared HDFS node2 lock
prevents concurrent Maven campaigns in the same source lane. Outputs use
unique `/tmp/mallory-hdfs-31-node2-full-v1` and
`/tmp/mallory-hdfs-32-node2-full-v1` directories; the frozen core resumes
from each checkpoint. The runner refuses mismatched existing output.

The frozen core still requires a runnable healthy JUnit with an observed
exact target, named DataNode and at least one pretarget injectable door
before it generates a queue. Those are required to start this target-guided
implementation, and no fresh healthy trace for these configs exists yet.
If that first run fails, `healthy_seed_invalid`, `healthy_no_injectable_door`,
or `fault_trials_not_attested` is an incomplete campaign, not a completed
negative result. No faulted target-retention or graph-path gate is added by
this package.
