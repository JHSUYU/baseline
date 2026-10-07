# HDFS-27 isolated actor-V2 launch and first fault trial

HDFS-43 explicitly released its node2 original-JUnit slot at
2026-10-07 10:50:13 UTC. Root assigned that slot to HDFS-27. The HDFS-27
runner is isolated under `/users/ZhenyuLi/hdfs-storage-v2-layout-isolated-20261007`;
the active HDFS-26/37 rollback code, checkpoint, and evidence were not copied
over or restarted. The new image copies the same six patched production/test
classes and has overlay digest
`a4f3ec05f0b534105fdac4084ef1386fa859bb0e5ed8602735502182a0dfc8e9`.
The two preexisting original healthy JUnit evidence trees and receipt were
copied byte for byte into the isolated anchor: 27 files, aggregate tree SHA256
`8158c9d6a0bb380c6483331bedb1a6aa2128e19f2ffa1cce00971d3ba687c680`.
The healthy receipt SHA256 is
`a29e09be452e37ddccd73fe88daf61516af1c2c5d2e07271c1f19698192549ed`.
No historical coarse fault trial was imported; the new checkpoint began at
zero completed/effective and seven pending plans.

The isolated image uses the following frozen controller files:

| File | SHA256 |
| --- | --- |
| `campaign.py` | `325d5399add30dabb20d4f6919b1b2ed181d79247c792924f6fc90ab0cecfdb2` |
| `guarded_locked_campaign.py` | `52375a7b87b1ae2cc66d2d5aee9b1bdf2d5bd876b413b1e07cc7767278bcb540` |
| `run_one_locked.py` | `094a5b58ca66a87c7afc762d3118add6abd3e0aecfe175c68e5c4d6859eca3ee` |
| `offline_smoke.py` | `6c211a1f813976b689f982e85c91fe7767f2de2816903cc7851a7af2e2c67f38` |

The initial node2 offline smoke lacked only the ASM util/analysis verifier
JARs, so no class check or cluster run was credited from that attempt. After
copying those exact ASM 9.6 verifier dependencies into this image, offline
smoke passed: all six patched classes ASM verified, actor/storage/peer/order
matching and expected versus novel target-throw context passed. This fixed
the smoke caller for the independent archive audit's new `(anchor,
pruned_exports)` parameters (tracked commit `7b51bd3319f18b37bd7f49ac4f39e1d796e60f5d`).

The first fault plan `1f24f5dc3d4daa29afd3` ran the unchanged
`TestDatanodeLayoutUpgrade#testUpgradeToIdBasedLayout` JUnit. Its locked
launch gate at 10:53:28 UTC saw three existing Java processes and
12,019,429,376 free bytes; it passed the 10-GiB floor. The original JUnit
returned 0 after 25.405 seconds. One `Client.getRpcResponse`
`SocketTimeoutException` matched/applied at raw seq 6 on
`episode=1/dn=1/dirs=dfs/data/peer=NN0`, and both the RPC endpoint and the
bound BP actor NameNode address were exactly
`localhost/127.0.0.1:46557`. The asynchronous pool thread rejoined through
its `StorageDirectory`; selected `BlockPoolSliceStorage.doUpgrade#L510-IF_ICMPEQ`
ran at raw seq 58 on the same actor and `dfs/data/current/BP-ID`, with
`equal=true`. There was no selected throw. Production feedback gained 30
JaCoCo probes, 12 branches, 29 lines, and four methods. The independent raw
audit passed with 1/1 strict, 1 effective, zero identity issues and zero novel
target signatures.

| First run raw file | SHA256 |
| --- | --- |
| `manifest.json` | `c27cf1063c7423ff0de1ee28a90f183a4fb959c779178a6e5505ea8d0112721c` |
| `runtime_trace.jsonl` | `650cc7eca0b63574451c9aa6b2a7d68ddd080f5a27de9a446959a99d6845d5fa` |
| `junit.log` | `ea52e0491f06ed37ca4bc9b811f3ef580cd5771eeb6427452bde20349675133c` |
| `faults.tsv` | `b78ccda9a975e7551972e01ab9cfe066d1adb766ceb138596deac70a5bfc7aa0` |
| `jacoco.exec` | `1c687c707ab8358abd329af56abdef3cbe3f56ea91644dc8e7b495db1e340095` |

The persistent node2 `hdfs27_actor_v2_budget` tmux resumed from this
one-plan checkpoint for the base 80-effective/max-eight-fault campaign,
conditional 128/max-ten. Each next original JUnit is under the shared launch
lock, with Java at most four before start and at least 10 GiB free disk;
resource-gate rejections are durably archived and retried. No completed
plan is rerun.
