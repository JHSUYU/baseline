# Source review of five startup storage checks

Hadoop 3.4.3 source under `hadoop-hdfs-project/hadoop-hdfs/src/main/java` was
read together with both V2 healthy traces. These five sites compare persisted
DataNode storage metadata with the `NamespaceInfo` supplied by the NameNode
during block-pool startup. They are legitimate cross-component coordination
checks, even though a mismatch exception can also be an intended rejection.

| Case | Exact source check | Compared state | Original JUnit context |
| --- | --- | --- | --- |
| HDFS-22 | `BlockPoolSliceStorage.doTransition`, lines 392–396 | Block-pool VERSION `namespaceID` versus NameNode `NamespaceInfo.namespaceID` | `TestDFSStartupVersions#testVersions` startup episode 1 and later variants |
| HDFS-23 | `BlockPoolSliceStorage.doTransition`, lines 398–401 | Block-pool VERSION `blockpoolID` versus NameNode `NamespaceInfo.blockPoolID` | Same block-pool startup paths as HDFS-22 |
| HDFS-25 | `BlockPoolSliceStorage.loadStorageDirectory`, lines 184–187 | Persisted block-pool `cTime` versus NameNode `NamespaceInfo.cTime`, after `doTransition` | Same original JUnit, after the version transition |
| HDFS-34 | `DataStorage.doTransition`, lines 740–744 | DataNode VERSION `namespaceID` versus NameNode `NamespaceInfo.namespaceID`, only when federation is unsupported by the stored layout | Later episode 3–8 legacy-layout variants; exact actor-bound I/O family is in `hdfs34_upstream_family.json` |
| HDFS-35 | `DataStorage.doTransition`, lines 749–752 | DataNode VERSION `clusterID` versus NameNode `NamespaceInfo.clusterID`, only when federation is supported | Federation-capable startup variants |

`BlockPoolSliceStorage.doTransition` first reads the storage directory's
VERSION file, then checks the persisted namespace and block-pool IDs before
choosing a regular startup or upgrade. `DataStorage.doTransition` likewise
reads VERSION and selects either namespace-ID or cluster-ID validation based
on the stored layout's federation support. The `NamespaceInfo` side is
obtained through the actor's verified NameNode RPC endpoint. This is the
file/RPC relation used to choose V2 fault points. HDFS-34 and HDFS-35 can
occur in different startup episodes because those two source branches have
opposite federation conditions.

An exact target throw alone is a candidate observation. A mismatched VERSION
file or `NamespaceInfo` may be a correct rejection by these guards. Every
candidate therefore requires identical-plan replay and review of the
persisted/RPC values and the original JUnit's expected outcome before a bug
mark is promoted.
