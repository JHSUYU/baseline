# HDFS-13, HDFS-18, and HDFS-37 source recheck

This offline review distinguishes an unchanged existing MiniDFSCluster JUnit
from a test-local workload adaptation. It does not add completed checks or
change the global checklist. `review.json` pins the Hadoop 3.4.3 source, old
calibration evidence, and any staged adaptation by SHA-256. Run
`python3 verify_review.py` from any directory to verify those pins.

| Case | Unchanged existing cluster JUnit | Follow-up |
| --- | --- | --- |
| HDFS-13 | `TestBlockTokenWithDFS#testEnd2End` misses the selected four-argument `Token` overload. The direct selected-overload tests use standalone managers. | Source-review gap; no qualifying cluster healthy seed identified. |
| HDFS-18 | `TestSecureAliasMap#testSecureConnectionToAliasMap` starts a PROVIDED MiniCluster but its measured run misses the duplicate-storage assertion. | An **unexecuted**, test-only second heartbeat adaptation is staged in `hdfs18-provided-heartbeat-v1`. It must be built and healthy-calibrated before admission. |
| HDFS-37 | `TestDFSRollback#testRollback` reaches the selected guard in its normal DN rollback phase, then deliberately reaches the selected throw in later invalid phases. `TestFileTruncate#testUpgradeAndRestart` sends DN ROLLBACK but lacks a DN-root `previous` directory, so `doRollback` returns before the selected guard. | An **unexecuted**, test-only normal-phase adaptation is staged in `hdfs37-normal-phase-v1`. It preserves the source test's valid rollback prefix and excludes its expected-failure suffix. |

Neither adaptation changes the production target or fabricates an injected
storage object. The HDFS-18 package was still untracked in the shared
workspace at this review; its owner must publish and repin it before a
dispatcher can use it. The HDFS-37 package is tracked. The existing runtime
results remain immutable. A source path is a reachability argument, not proof
that a fresh healthy JUnit passed.
