# HDFS-33/34 source and healthy GO audit

This audit applies to the original-102 selected checks and the staged
`hdfs33-34-fresh-healthy-v2` package. `source-receipt.json` pins the Hadoop
source, compiled target and test classes, old-image fixture, staged configs,
site catalogs, and archived calibration evidence by SHA-256. Run
`python3 -B verify_source_receipt.py` on node0 for a read-only, no-JVM check.
The source commit is `9d50c6884666e794e45102260a4017bb31802e1b`;
the full source digest is
`825878fdb546b98f0c1c17339d83625e62fa0aadd5b76284a2640fac3926bef7`.

## HDFS-33

The selected target is the `DataStorage.VolumeBuilder.build()` assertion
`bpStorage != null` at `DataStorage.java:259`. The compiled selector records
both `@259:branch:4` and `@259:branch:5` before `@259:throw:1`. The existing
`TestDataNodeHotSwapVolumes#testAddOneNewVolume` creates one DataNode and
hot-adds a volume (`TestDataNodeHotSwapVolumes.java:403-411`). The archived
no-fault run of this same selector returned 0, reached one exact check
occurrence without the selected `AssertionError`, and passed JUnit 1/0/0.
Its target events have `node: unknown`, so it is not a named healthy seed.

`StorageLocation.makeBlockPoolDir:276` calls `DiskChecker.checkDir`, a typed
physical `IOException` door. `DataStorage.prepareVolume:338-345` calls it
before `getBlockPoolSliceStorage` inserts `bpStorageMap[bpid]` and before a
builder is returned. A fault that leaves the new directory absent is caught
inside `makeBlockPoolDir`, but the later
`BlockPoolSliceStorage.loadStorageDirectory:161-166` rejects that missing
directory. `FsDatasetImpl.addVolume:501-545` rethrows preparation errors or
later volume-construction errors before `builder.build`. If the directory
already exists and the builder does run, the map entry was inserted before
the check. No reviewed physical I/O fault here is likely both to leave the
map lookup null and retain this builder's check. HDFS-33 stays an identity
observation candidate, not the next fault-oriented healthy GO.

## HDFS-34

The selected target is the pre-federation namespace guard at
`DataStorage.doTransition:739-744`, specifically the `@739:branch:5`
predicate before the selected `@744:throw:1` `IOException`. The staged
existing `TestDFSUpgradeFromImage#testUpgradeFromRel22Image` unpacks the
0.22 image and starts four DataNodes under `StartupOption.UPGRADE`
(`TestDFSUpgradeFromImage.java:296-299,598-604`). The pinned archive has
two NameNode and eight DataNode `current/VERSION` files, all with
`namespaceID=-386152743` and `layoutVersion=-33`. That supports a
nonthrowing pre-federation guard, but no fresh run of this selector has
confirmed exact target reach or named DataNode identity. The archived
HDFS-34 calibration used **a different test**,
`TestDFSStartupVersions#testVersions`, and threw the selected exception;
it cannot serve as this healthy seed.

`BPServiceActor.retrieveNamespaceInfo:260` calls the NameNode
`versionRequest` RPC and catches `IOException` at 265-270, retrying while
the actor runs. A later successful reply flows through
`connectToNNAndHandshake:306`, `BPOfferService.verifyAndSetNamespaceInfo:394`,
`DataNode.initStorage:2259`, and `DataStorage.doTransition:296` on the
same DataNode. This is a source-backed pretarget physical RPC door **likely
to retain** a later target occurrence after one injected transport error.
It is not shown to change either namespace ID. The `Properties.load` call
in `StorageInfo.readPropertiesFile:272` reads the local `VERSION` data used
by the guard, but an injected read `IOException` propagates from storage
transition and can abort startup, so it is diagnostic only.

## Next GO

After HDFS-20 releases the node2 HDFS source/build lane, **admit one
HDFS-34 healthy-only run** from the staged v2 package, subject to dispatch's
normal fresh-output and capacity checks. Require Surefire 1/0/0, the exact
nonthrowing `@739` guard on a named DataNode and epoch, zero selected `@744`
throws, loaded class/catalog SHA attestation, and an observed typed
`versionRequest` door preceding that DataNode's storage transition with a
root-free event-time path. Preserve individual DataNode and storage-directory
occurrences across the four-DataNode startup. If any condition fails, classify
the healthy seed as unadmitted.

Keep HDFS-33 on hold for fault-oriented admission. Its one-DN named-identity
probe can be scheduled later if that observation itself is needed, but the
staged directory door does not justify a fault pilot. Neither case has a
fault or full-campaign GO. For HDFS-34, a pilot would additionally need a
source-backed account of how a retained RPC error could affect the namespace
comparison; target retention alone does not provide that causal mechanism.

No JVM, fault trial, full campaign, or checklist edit was performed for this
audit.
