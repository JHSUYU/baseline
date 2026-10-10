# HDFS-33/34 fresh node2 healthy admission

These are two case-local **healthy-only** configurations for the original-102
DataStorage checks. Both are pinned to Hadoop 3.4.3 commit
`9d50c6884666e794e45102260a4017bb31802e1b`, the frozen fa5f Mallory
core, the immutable agent, the case adapter, compiled target and test classes,
and the site file. `provenance.json` records hashes and the node0 source tree
equivalent to the node2 `hdfs-identity-v8` tree. Each config requests one
fault-free selected JUnit and disables automatic campaign promotion.

| Case | Existing JUnit | Selected check | Typed pretarget door |
| --- | --- | --- | --- |
| HDFS-33 | `TestDataNodeHotSwapVolumes#testAddOneNewVolume` | `DataStorage.VolumeBuilder.build` line 259, `assert bpStorage != null` | `StorageLocation.makeBlockPoolDir` line 276, `DiskChecker.checkDir`, `IOException` (diagnostic only). |
| HDFS-34 | `TestDFSUpgradeFromImage#testUpgradeFromRel22Image` | `DataStorage.doTransition` namespace guard at lines 739-744 | `BPServiceActor.retrieveNamespaceInfo` line 260, `versionRequest` retry `IOException`; `StorageInfo.readPropertiesFile` line 272, `Properties.load` diagnostic `IOException`. |

HDFS-33's test creates one DataNode and hot-adds a new volume. The directory
check is physically before `DataStorage.prepareVolume` inserts the block-pool
storage map entry and before the builder check. `makeBlockPoolDir` catches
`IOException` from `DiskChecker.checkDir`, but the new block-pool directory
may then be absent. `BlockPoolSliceStorage.loadStorageDirectory` rejects a
nonexistent directory; failure can prevent `builder.build` from running.
This typed door is for healthy path and actor observation, **not** an admitted
target-retaining fault point. The prior healthy JUnit passed 1/0/0 but marked
the selected target actor `unknown`. The fresh gate must resolve that identity.

HDFS-34 uses the existing 0.22 image fixture with matching namespace IDs,
not the original `TestDFSStartupVersions#testVersions` method that
intentionally triggers the selected exception. `versionRequest` is in the
`BPServiceActor.retrieveNamespaceInfo` retry loop before DataNode storage
transition; it is a source-backed candidate for target retention. The
`VERSION` file read is an ancestry diagnostic because its injected failure
may abort startup. Neither door nor the named nonthrowing target has been
observed together in a fresh healthy run.

## Static checks and dispatch order

On node0, run `python3 -B preflight.py HDFS-33 --static` and then the HDFS-34
equivalent. Both archived static receipts pass. The preflight verifies the
source digest, all pinned class, release, fixture, config, and site hashes,
the one-run gate, typed door identity, and Mallory static frontier. It starts
no JVM. On node2, dispatch repeats `preflight.py HDFS-33` and then HDFS-34
without `--static`, after assigning the shared HDFS source lane. Queue
**HDFS-33 first**, then **HDFS-34**, with no overlap on that source/build
lane. HDFS-33 is the shorter one-DataNode actor-identity probe; HDFS-34's
four-DataNode old-image upgrade is the heavier candidate.

After the node2 preflight and dispatch admission, the corresponding command
is `MALLORY_DISPATCH_ADMITTED=1 ./run_healthy.sh HDFS-33` (then HDFS-34).
The runner holds the shared node2 HDFS lock and refuses an existing output.

For each live healthy result, require Surefire 1/0/0, the exact nonthrowing
target on a concrete DataNode and epoch, the loaded target class and site
catalog matching pins, and the typed pretarget door observed on the relevant
actor. Record the root-free event-time path and offline audit as outcomes.
Do not infer actor identity from JUnit success or promote a fault campaign
from a typed door alone. The already staged 80-trial full packages remain
pending until the fresh named healthy admission is independently reviewed.

This package contains no fault plan. No JUnit, fault trial, or full campaign
ran while preparing it.
