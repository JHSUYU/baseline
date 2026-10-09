# HDFS-24, HDFS-34, HDFS-37 source-only handoff

`source-receipt.json` pins the Hadoop 3.4.3 source commit, selected JUnit and
target classes, prior calibration, and the two dispatchable healthy-only
configs. No JVM, Docker container, or fault trial was started here.

| Case | Decision | Selector |
| --- | --- | --- |
| HDFS-24 | Candidate healthy probe | `TestFileTruncate#testUpgradeAndRestart` |
| HDFS-34 | Candidate healthy probe | `TestDFSUpgradeFromImage#testUpgradeFromRel22Image` |
| HDFS-37 | Hold: no suitable existing healthy selector identified | None |

HDFS-24 uses a persisted block-pool directory, then restarts the NameNode
with `UPGRADE`. `FSImage.doUpgrade` advances namespace `cTime`, and
`BlockPoolSliceStorage.doTransition` should reach the selected `@414/@415`
check on the older persisted block-pool `cTime`. The previously staged 0.22
image test is unsuitable for HDFS-24: `DataStorage.doUpgradePreFederation`
formats block-pool storage with the new `cTime`, so the selected check is
skipped. HDFS-34 uses that same 0.22 image to enter the pre-federation
namespace check in `DataStorage.doTransition` with matching namespace IDs.

Both configs explicitly instrument `BPServiceActor.retrieveNamespaceInfo` at
its line 260 `versionRequest` call. One injected `IOException` there is caught
and retried by that method; a later successful request can still lead to the
storage check. The door is a source-backed candidate, not a proven causal
path. The healthy run must prove the exact check on a named DataNode, no
selected target throw, passing JUnit, a woven door in the site catalog, and a
root-free observed event-time path. The configs contain one fault-free trial
and cannot auto-promote to a campaign.

HDFS-37's original `TestDFSRollback#testRollback` reaches the exact comparison,
but the same version matrix deliberately throws the selected exception. The
staged `TestFileTruncate#testUpgradeAndRestart` sends `ROLLBACK` to DataNodes,
but its preceding upgrade starts those DataNodes with `REGULAR`. DataNode root
storage retains the current layout, so `DataStorage.doRollback` returns when
`previous` is absent, before the selected comparison. Do not dispatch the
older pending-triage-v1 HDFS-37 config as a healthy probe.

Dispatch should allocate an idle isolated source/build lane. At preparation,
node0 had 5.5 GiB free; the HDFS-34 old-image run was previously estimated to
need about 1 GiB transient space, so it must not run on node0 at that free
space level while preserving the 5 GiB floor. Recheck free space before any
admission.
