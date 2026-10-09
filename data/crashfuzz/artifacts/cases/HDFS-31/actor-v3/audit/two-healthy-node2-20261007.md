# HDFS-31 V3 two original healthy JUnits on node2

The actor V3 offline image ran the unchanged Hadoop 3.4.3
`TestDiskError#testDataTransferWhenBytesPerChecksumIsZero` in the original
embedded cluster, with separate scratch directories and dynamic ports. Each
seed acquired `/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/jvm-start.lock`
before starting a JVM and checked at most four existing Java processes and
at least 10 GiB free disk. HDFS-37's shared rollback JUnit continued under
the same lock without interruption. Historical HDFS-31 coarse-actor trials
contribute zero to this V3 calibration and future budget.

| Seed | UTC start–finish | Original JUnit | Time | Exact raw audit |
| --- | --- | --- | ---: | --- |
| healthy-a | 13:53:18.959–13:53:37.474 | pass, exit 0 | 18.515 s | 2 registered DNs, 2 adopted BP actors, 2 pool adds, 1 same-block transfer→target, 10 bound RPC, 6 eligible RPC, 0 target throws, 0 issues |
| healthy-b | 13:56:32.141–13:56:47.908 | pass, exit 0 | 15.767 s | same counts and 0 issues |

Both seeds selected the same logical target actor
`episode=1/dn=1/dirs=dfs/data,dfs/data` and had six stable actor-bound
producer selectors. The doubled directory text reflects the original test's
configured paths; the raw DataNode UUID, BP ID, DataNode object,
`BPOfferService` object, and target block joins are independently checked in
each run. UUID values can change between fresh clusters and are not used as
a cross-run equality requirement. The common patched-class instrumentation
digest is
`24435f63c124d259c328d441361f364b0dcd89e6259382f1110b2f2ab39d41f5`.
The two-seed independent receipt is `pass=true`, six stable selectors, and
zero issues (receipt SHA-256
`cd1940c2f93b6cdde014fa4dbfdcecfc7c062970962abf1d723a2e8c7ff18de9`).

Before seed A, the healthy supervisor gained a complete-seed boundary option
so its raw actor evidence could be reviewed before B. Node0 and node2
`guarded_healthy.py` SHA-256 both equal
`971f8a4b1dfc931d592c8dae3ee8fa861bee4567649eb310616013695073a1c0`.
The patched target classes and original JUnit did not change. The earlier
offline stage tree digest predates this controller-only revision; the overlay
digest above remains the runtime gate.

All 19 regular files from the two healthy directories plus their receipt,
totaling 14551936 bytes, were mirrored from node2 to node1 and rehashed
there. The immutable mirror manifest SHA-256 is
`6c9548486344a1c7f72ed99e5aff8b5a5c32827fb64dd469a551842e900bddde`;
node1 verification had zero mismatches. The source and mirror evidence anchor
is `/users/ZhenyuLi/hdfs31-actor-v3-20261007/evidence` on each host.

This establishes the healthy actor/target gate. The separate fault pilot is
bounded to two new completed plans; neither healthy seed is counted as a
fault trial.
