# ZooKeeper pending checks: source-only triage v1

Scope: original checks ZOOKEEPER-04, -05, -06, -10 and -12 on the exact
ZooKeeper `release-3.8.7` source commit
`9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae`. `source-review.json` records
the SHA-256 of each selected source and JUnit file, along with immutable prior
calibration and pilot receipts. This directory was prepared without launching a
JVM and does not change the 102-row checklist or any running release.

All five checks have an existing cluster JUnit candidate. Thus **none** is a
`no_suitable_cluster_test` conclusion. Existing passing healthy traces reach
the exact nonthrowing target for 04, 05, 06 and 12. ZK10 is source-only so far.

| Check | Existing JUnit and current evidence | Next bounded step |
| --- | --- | --- |
| 04 | `ConnectionMetricsTest#testRevalidateCount`; the reconnect on zk2 reaches `processConnectRequest`'s client-zxid guard. Six prior faults applied, but none retained an exact same-occurrence or observed causal path to a later selected check. | Hold. An exception at `zookeeper.client.connect.read` aborts that connect attempt before the comparison; the later check is another attempt. Admit only after an exact client reconnect retry handoff is observed, with a fault-to-check path on the same client/session, named server and lifecycle. Do not reuse the actor-wide root. |
| 05 | `QuorumRestartTest#testRollingRestart`; the follower's leader-epoch guard runs. Previous six-fault pilot had zero causally retained selected checks. | Use the already compiled `following-retry-v3` source overlay. `ZOOKEEPER-05.healthy-only.json` pins a **fresh** strict seed to its compiled Follower and the immutable thread-ID agent. Admit a short fault pilot only after a healthy I/O→check path and exact target catalog are observed. On fault, require a scoped old `FOLLOWING` attempt → unique retry task submit/claim → new attempt → selected check path. |
| 06 | Same rolling-restart JUnit reaches `Leader.waitForEpochAck` four times; old graph had no I/O path. | The isolated ACKEPOCH packet-object handoff overlay is compiled and source pinned. Its pre-existing `ackepoch-healthy-v1/command.json` is only **prepared**, not executed; the strict `ZOOKEEPER-06.healthy-only.json` is staged here. Run one healthy preflight when the ZooKeeper lane is free; require paired ACKEPOCH SEND/RECV and its unique `StateSummary` handoff into the named leader check before any fault. |
| 10 | `ObserverMasterTest#testInOrderCommits` is mapped but has no runtime seed and performs over 20,000 async writes across the two parameter variants. | `ZOOKEEPER-10.healthy-only.json` first tries the existing, shorter `ObserverMasterTest#testObserver` method. It also has true/false variants. Only true enables ObserverMaster; require exact `removeProposedPacket` check hits in the true variant. If the shorter test misses, return to the original selector under a separate time ceiling. The current packet hook scopes REQUEST, not the PROPOSAL/COMMIT-to-ObserverMaster handoff, so a root-free packet path is an additional explicit gate. |
| 12 | `CurrentEpochWriteFailureTest#testReadCurrentEpochFromAcceptedEpochTmpFile` reaches the accepted/current epoch guard. Six prior generic IOException faults yielded zero causally retained selected checks. | `ZOOKEEPER-12.sites.json` gives the pinned `readLongFromFile` `BufferedReader.readLine` door `java.io.FileNotFoundException`. The source catches this subclass, assigns the fallback epoch, then continues to the selected check, whereas generic IOException escapes to the outer startup failure. First run the healthy-only config and verify that the door is catalogued with this precise exception class on the named target occurrence. A later small pilot must select the `acceptedEpoch` read's observed ordinal and prove exact postfault check retention. |

The four staged configs are `calibration_only`, use one trial, set
`auto_promote_if_healthy=false`, and pin the immutable agent/core, source overlay
receipt, compiled target class, site file, and expected test source hashes.
`prepare.py` reproducibly regenerates them and `prepared.json` records their
hashes. These configs point to isolated node2 source overlays and are not
dispatch admissions. The source overlay, agent and site artifacts must be
copied and SHA checked on the execution host before running. No full campaign
is authorized by this preflight.

Admission remains an evidence gate: passing JUnit, exact loaded class hash,
named peer, exact nonthrowing check, and a root-free time-respecting I/O path
to the target in the healthy run. A later fault trial must show exact fault
application and the selected check *after* the fault on the same bounded causal
continuation. For 04 and 12, the previous healthy local timeline alone does
not establish a graph path. An exception or unrelated later target check does
not count as a confirmed new bug.
