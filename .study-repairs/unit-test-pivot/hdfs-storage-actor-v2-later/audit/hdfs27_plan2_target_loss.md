# HDFS-27 plan 2: storage read fault prevents target execution

At the node2 isolated V2 checkpoint, `TestDatanodeLayoutUpgrade#testUpgradeToIdBasedLayout` plan `3605659628b285363ed2` completed once (25.563 s; original JUnit exit 1). The controller applied its sole `IOException` at `BlockPoolSliceStorage.readProperties` VERSION_READ, raw sequence 9, on `episode=1/dn=1/dirs=dfs/data`, storage `dfs/data/current/BP-ID`. The selected `BlockPoolSliceStorage.doUpgrade#L510-IF_ICMPEQ` check did not execute after the fault. Independent raw audit: 2/2 plans strictly applied, 1/2 effective, 0 target exceptions, 0 audit issues.

The original test configures one DataNode and one unmanaged data directory in `TestDatanodeLayoutUpgrade.java:42-53`. The JUnit log records the injected read exception in `BlockPoolSliceStorage.doTransition:388`, `DataStorage` rejecting that directory, `All specified directories have failed to load`, then `MiniDFSCluster.waitClusterUp` timing out. This is a direct startup failure from the injected fault; the selected target was lost. It is an attempted, ineffective trial and does not establish a coordination bug. The first plan `1f24f5dc3d4daa29afd3` remains the one effective plan; no plan was repeated.

Raw node2 evidence: `/users/ZhenyuLi/hdfs-storage-v2-layout-isolated-20261007/evidence/layout-upgrade-constructor/runs/3605659628b285363ed2/attempt-1/`.

| File | SHA-256 |
|---|---|
| `manifest.json` | `18c110acb14364d195be81e62d29a0f50ac2bd14e7fae2e31f3bdeeaa75d7320` |
| `runtime_trace.jsonl` | `71671d474c34afc0f01f70a0ee8815cbab6890d4e68e846cb8f0c45ff971516a` |
| `junit.log` | `0cb0dcdc980f4fca2ee79e4a3ee992d641982ae089f26c607db714a7223e60aa` |
| `faults.tsv` | `9f4334c6e06f0c554a3f68877e52348ebed43d0d3d92cea114d3e42ed87e12f8` |
| `jacoco.exec` | `7974243b9c8007c618d362646be7b21f1245302fd14362ca658a92bb7e6770b7` |

Original source: `/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3/hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/TestDatanodeLayoutUpgrade.java`, SHA-256 `69ae29561b9446b3817c3a37c28464e8cb38b960bcac8a4367d982990c0cfc99`.
