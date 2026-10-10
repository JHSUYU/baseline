# HDFS-33/34 node2 full stage

This case-local package is staged without running Java. Each config has an
80-trial, 3600-second, at most three faults per trial budget and uses the frozen
fa5f Mallory core. Dispatch must first run the separate healthy-only candidate
from `hdfs33-34-node2-stage-v1`, then inspect its JUnit 1/0/0 result, exact
nonthrowing target on a named DataNode and epoch, loaded target class/catalog,
and at least one eligible pretarget injectable I/O door. The full campaign also
starts and attests its own healthy seed. A fresh named healthy result is still
pending for both cases, so neither full runner is admitted yet.

| Case | Existing MiniDFSCluster JUnit | Selected check | Open source-backed gap |
| --- | --- | --- | --- |
| HDFS-33 | `TestDataNodeHotSwapVolumes#testAddOneNewVolume` | `DataStorage.VolumeBuilder.build` line 259, `assert bpStorage != null` | Prior JUnit 1/0/0 reached the check with unknown actor. Auto I/O doors remain unverified; no retained I/O path to a null `bpStorageMap` is proven. |
| HDFS-34 | `TestDFSUpgradeFromImage#testUpgradeFromRel22Image` | `DataStorage.doTransition` namespace guard at line 739, selected throw at line 744 | The 0.22 image test starts four DataNodes. Typed RPC retry and VERSION read doors are source candidates; runtime ordering and named target reach are unverified. |

`TestDFSRollback#testRollback` is the HDFS-26 selector for a separate
`BlockPoolSliceStorage.doRollback` guard. It is not a selector for either
DataStorage check in this package.

Graph path quality and offline causal audit are reported outcomes. They do not
gate healthy admission or completion. The controller still requires JUnit
success, exact nonthrowing target on a named actor, a valid target catalog, and
at least one eligible pretarget injectable I/O door. Report the natural
controller terminal status and the actual count of completed fault trials.

Run `python3 preflight.py HDFS-33 --static` and the matching HDFS-34 command on
node0 for SHA, source, artifact, budget, and Mallory static checks without a
JVM. Dispatch can repeat the commands without `--static` on node2. After a
fresh named healthy result is admitted and a separate GO, dispatch may use
`MALLORY_DISPATCH_ADMITTED=1 ./run_full.sh HDFS-33` or HDFS-34. The runner holds
the shared node2 HDFS lock, refuses an unrelated output, and uses distinct
output directories for the two campaigns.
