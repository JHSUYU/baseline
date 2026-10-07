# HDFS27 target in the HDFS24 original JUnit trace

Read-only comparison of the two calibrated workloads using the same storage
V2 overlay SHA256 `a4f3ec05f0b534105fdac4084ef1386fa859bb0e5ed8602735502182a0dfc8e9`:

| Original JUnit | HDFS27 `doUpgrade` line 510 check in healthy A/B | Actor and storage | Outcome |
| --- | --- | --- | --- |
| `TestDFSUpgrade#testUpgrade` (HDFS24 workload) | 6 / 6 | Episodes 4, 6, 13 and 15, one or two `dfs/data1`/`dfs/data2` volumes | `namespaceID == nsInfo.namespaceID` in all 12 observations; no selected assertion throw |
| `TestDatanodeLayoutUpgrade#testUpgradeToIdBasedLayout` (HDFS27 workload) | 1 / 1 | Episode 1, `dfs/data` volume | equality true in both observations; no selected assertion throw |

The HDFS24 workload does reach **the exact HDFS27 source check** in both
healthy seeds. The second HDFS24 actor V2 fault plan also shows a strict NN0
RPC fault on episode 6 / DN 1 at seq 91 followed by that same actor and
storage's HDFS27 target at seq 151, equality true. The first HDFS24 file
fault has zero postfault same-actor HDFS27 checks. These HDFS27 events are
supplemental observations; the running HDFS24 checkpoint has only HDFS24 in
`case_ids` and credits none of them to HDFS27.

The workloads prepare different on-disk states. `TestDFSUpgrade#testUpgrade`
loops over one/two generated storage directories and valid/invalid upgrade
states (`TestDFSUpgrade.java:225 onward`). HDFS27's original JUnit unpacks a
historical DataNode layout image, sets `dfs/data`, and calls
`TestDFSUpgradeFromImage.upgradeAndVerify` (`TestDatanodeLayoutUpgrade.java:
42–56`). Thus a shared-JUnit campaign could test the same line under the
HDFS24 upgrade states, but it would **not** exercise the historical image
transition of the HDFS27 original workload.

After HDFS24's current budget reaches a complete boundary, a dual-case
controller may reuse one original `TestDFSUpgrade` JUnit execution for both
checks only if it first defines separate healthy signatures, separate
actor/storage postfault gates, and separate effective denominators. It must
label HDFS27 as the `TestDFSUpgrade` supplemental workload. The direct
HDFS27 `TestDatanodeLayoutUpgrade` workload remains a distinct calibrated
campaign for the historical layout scenario. Do not retroactively import
HDFS24 effective counts or old HDFS27 coarse counts into either budget.
