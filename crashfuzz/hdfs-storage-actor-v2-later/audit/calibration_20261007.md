# HDFS-24/26/27/37 original JUnit healthy calibration

The shared actor-aware overlay ran on node2 from isolated image
`/users/ZhenyuLi/hdfs-storage-v2-later-a4f3ec05f0b5`. The source/build archive
SHA-256 is `cf9d396166056aca80bd0738d2439abc68702de5bc6b096dafee37a10511a86f`;
all six manifests report overlay digest
`a4f3ec05f0b534105fdac4084ef1386fa859bb0e5ed8602735502182a0dfc8e9`.
Before each seed, `host_gate.py` observed three existing application JVMs,
more than 10 GiB free, complete dependencies, and the same overlay digest.
Each run used a separate scratch tree and the unchanged Hadoop 3.4.3 JUnit.

| Group / case | Seed a UTC, seconds | Seed b UTC, seconds | Exact target checks and healthy throws per seed | Stable same-actor upstream selectors |
| --- | --- | --- | --- | ---: |
| rollback / HDFS-26, HDFS-37 | 08:44:08.758, 46.764 | 08:45:38.683, 49.944 | HDFS-26: 6 / 0; HDFS-37: 12 / 3 expected `InconsistentFSStateException` | 8 / 10 |
| upgrade / HDFS-24 | 08:47:04.383, 44.120 | 08:48:28.608, 40.406 | 18 / 3 expected `IOException` | 24 |
| layout_upgrade / HDFS-27 | 08:50:05.954, 16.968 | 08:51:03.451, 15.018 | 1 / 0 | 3 |

All six original JUnits exited 0. The shared rollback JUnit registered and
entered 11 DataNode actors per seed, bound 48 NN0 RPC responses and 32 file
I/O points, and yielded 80 stable global I/O selectors. Upgrade registered
and entered nine actors, bound 40 RPC and 23 file points, and yielded 63
stable global selectors. Layout upgrade registered and entered one actor,
bound five RPC and two file points, and yielded seven stable global
selectors. Both HDFS-27 target events occurred at raw sequence 12 on
`pool-17-thread-1`, joined through the actual storage object to
`episode=1/dn=1/dirs=dfs/data` and `dfs/data/current/BP-ID`. The target
branch was `doUpgrade#L510-IF_ICMPEQ equal=true` in both seeds.

The independent two-seed calibration receipts are `pass` with no issues:
stable target actor sets, stable expected-throw signatures, exact endpoint
mapping, nonempty JaCoCo and branch feedback, and one or more target-before
same-actor I/O selectors for every case. HDFS-24 and HDFS-37's expected
throws are signatures of the original test's deliberate invalid storage
states; they are not bug observations. Every raw trace was hashed again
against its seed receipt. The six complete evidence trees (including raw
trace, JaCoCo, branch list, original JUnit log, gate, and receipt) were copied
from node2 to the same isolated path on node1; both trees have aggregate
SHA-256 `cfb0eaab142f25ea1437aab4570b3b5bf09d9547b825b2d777e8be0b15472203`.

These are healthy calibrations only: **zero fault trials and zero effective
trials** in the new V2 groups. The historical coarse results remain separate.
Each group's `campaign.py` can begin from its own passing receipt when a
cluster slot is allocated. It must count an effective trial only after all
ordered faults apply and the exact same-actor, same-storage target occurs
after the last fault; healthy expected throws are compared by signature.

The temporary disk-space gate used a separate, verified archive of historical
ZOOKEEPER-02 GraphChecker traces. Its new 52-file manifest is mirrored on
node2 and node1 with SHA-256
`30cb757869d3970f3626271290d09fa4f35e813c8ca41360a80c527d6cd2632d`.
The previous 248-row manifest remained byte-identical, SHA-256
`8f0e5aad71206754223fcc3a96f630c0315c0f6287433d35fa7663c79e6d6410`.
