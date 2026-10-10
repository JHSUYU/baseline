# HDFS-34 old-image source and JUnit admission

This is a healthy-only, source-backed candidate for
`TestDFSUpgradeFromImage#testUpgradeFromRel22Image`. The test unpacks the
0.22 HDFS image and starts a four-DataNode `MiniDFSCluster` with
`StartupOption.UPGRADE`. The archive's two NameNode and eight DataNode
`current/VERSION` entries share namespace ID `-386152743`; the DataNode
layout is pre-federation `-33`. `DataStorage.doTransition` reads the persisted
`VERSION` before its selected namespace guard. Source and compiled bytecode
support reaching `@739:branch:5` on the nonthrowing side of the selected
`@744:throw:1` `IOException`. Runtime reach remains unverified.

The site file names two typed I/O doors before that check:

| Door | Source behavior | Admission role |
| --- | --- | --- |
| `BPServiceActor.retrieveNamespaceInfo` line 260, `DatanodeProtocolClientSideTranslatorPB.versionRequest` | `IOException` is caught and the request retries while the actor runs. | Candidate retained RPC door; completed reply ancestry and postfault target retention remain unobserved. |
| `StorageInfo.readPropertiesFile` line 272, `Properties.load(InputStream)` | Reads the persisted `VERSION` used by the guard. | Diagnostic file-read ancestry; an injected read error may abort DataNode startup, so it is not a promoted fault door. |

The healthy config adds `StorageInfo` to instrumentation scope and pins a
scoped copy of the agent (SHA-256
`38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9`)
and v10 HDFS adapter (SHA-256
`1f65f6346288e92e514f6e815be35aea6d446cd0432a429fa130ad9aab581585`).
The config SHA-256 is
`69c7fea84c8cb14712efa0a1a87374129847b7ddd22ad58366387881c56fce83`;
the site file SHA-256 is
`a43cf63598a9e36f41bb4c8a79fb8b8d4d2272c92135869719d39bf9387d4112`.
`source-receipt.json` pins all source, class, fixture, and release inputs.

Run `python3 check_offline.py` from this repository to verify hashes,
compiled call sites, target branch ordinal, fixture values, and Mallory
config admission without starting a cluster. This check passed on 2026-10-09.
The original `TestDFSStartupVersions#testVersions` intentionally includes
mismatched versions and previously threw the selected exception, so it is not
a clean healthy selector.

Dispatch must grant a separate idle HDFS source/build lane after HDFS24 and
recheck disk headroom before a live healthy run. The earlier old-image review
used a 1 GiB transient planning allowance and a 5 GiB host reserve. The live
gate requires JUnit 1/0/0, the exact nonthrowing check on a named DataNode,
a woven explicit door, matched typed response when using the RPC door, and a
root-free event-time pretarget path from an eligible I/O door. No fault or
full campaign is admitted until that named healthy and strict path gate
passes. Neither a cluster JVM nor a fault trial was started for this handoff.
