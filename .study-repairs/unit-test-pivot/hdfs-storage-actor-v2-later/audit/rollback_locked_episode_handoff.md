# HDFS-26/37 rollback: locked handoff and episode pilot

The old node2 rollback controller ended at a complete original-JUnit boundary:
84 distinct plans, HDFS-26 42 effective, HDFS-37 41 effective, no in-flight
plan, checkpoint SHA-256 `0a69ac8adc458cbc2efe66b1926ba46be274add9d32d49f4bca9309de7c15fcb`.
Its final trial `4e3aa6ba9223fbfbd279` was JUnit pass/strict and its raw
trace matched the state SHA. The old outer controller was stopped only after
that JUnit and checkpoint completed, then terminated; no old controller or
JUnit remained when the new one started. The new controller uses the same
overlay digest `a4f3ec05f0b534105fdac4084ef1386fa859bb0e5ed8602735502182a0dfc8e9`
and a node-local shared launch lock covering the Java≤4 and free≥10 GiB gate
and the original JUnit. The prior controller source SHA was
`9a9789edbba727742e9c2ce5a1c2feca79e2d21705e630f84173819434ec0ead`;
the prior campaign selector SHA was
`def5991586e4fcda884a636a72990450dba33cd718644fa28aeec5dfdb5217ac`.

The first two locked plans preserved ordinary deep-plan priority: #85
`a162bcc0b0dda9a85302` (HDFS-37, episode 11, 89.759 s) and #86
`320a7b7f46567d7853dc` (HDFS-26, episode 5, 91.732 s) each completed the
unchanged JUnit with exact ordered faults, same-actor target hits, and no novel
selected exception. Both immutable locked receipts and trace hashes passed the
independent audit. At 86 completed, the complete-boundary checkpoint SHA was
`bc3830ea2870c737f0aaf7796170fe1796c92d0b199f966bc7347590ad890a20`.

At that boundary, the controller kept one bound-RPC episode exploration pick
per ten plans but moved its phase to count 86. The source SHA before this
phase shift was `f5d242ab29f5e88c08ee3562352cf42340f092e2bffa411c537d6aed691d2b27`;
afterward it was `17a64e1f50c730f6b84da5dc6349e7b21bde7b8d79d62641361a8a4e7bf50150`.
Offline synthetic smoke passed, and a deep-copy pick of the real checkpoint
selected previously unsampled HDFS-26 episode 15 without changing the queue
on disk.

The resulting #87 `1577c76db64f0c88d125` ran the original
`TestDFSRollback#testRollback` JUnit in 55.385 s, exit 0. Its one NN0 RPC fault
strictly matched actor `episode=15/dn=1/dirs=dfs/data1,dfs/data2`; the selected
HDFS-26 check executed four times afterward on that actor, with zero selected
throws. The locked gate and campaign returned 0. Independent raw audit after
the trial: 87/87 strict plans, HDFS-26 44 effective, HDFS-37 42 effective,
zero identity issues, zero novel target signatures, and no in-flight plan.
No prior plan or effective count was replayed or reclassified.

| #87 raw evidence | SHA-256 |
|---|---|
| `manifest.json` | `397196b371087453d819e7d39ffce5da8bcf79207c6ad6ffdc116298d1ba7f50` |
| `runtime_trace.jsonl` | `6a94b7ad109afc023fbb7bd097a71773296f0977250c83321f76ecff7d79dea4` |
| `junit.log` | `7b9e8dd71252b7f60cdd74de2ea40343b29c5811f263e0a607779be4614e437d` |
| `faults.tsv` | `c5d1a4b92121cf6f59a52ede4afb699f621c0ae51d09851c040d96e198c38441` |
| `jacoco.exec` | `1560a9bd30409840121881936eb3c24d01b711c4e07787f461cca6c87a89c222` |
| `locked-plan-0087.json` | `d005e444367f498c6cb3ddae1876100f830d1a21060e5cbf54d4e05fa02175c3` |

The post-pilot checkpoint SHA is
`37bd6ab5ca4c389c3618d51f591145584bc93832550c31aabb3a3bc28731e811`.
The isolated code image is `/users/ZhenyuLi/hdfs-storage-v2-rollback-episode-20261007`;
the authoritative state and raw runs remain in the original rollback evidence
anchor on node2.
