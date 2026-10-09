# HDFS-28 shared HA RPC V3 natural handoff

The original `TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization`
V2 controller naturally stopped after 320 selected attempts with 44 strict,
same-owner postfault HDFS-28 checks. Its checkpoint had no active trial and
the V2 log ended with `terminal attempt_cap_inconclusive`. The other shared
targets were at 103 postfault checks each, but their terminal results retain
their separate earlier prefix and are not recounted here.

`target_rpc_v3.py --preview` found 12 unseen `HDFS_RPC` and 12 unseen
`HADOOP_IPC` singleton selectors in prior effective traces, each with verified
physical actor/recovery-root identity and a later HDFS-28 guard. The independent
full raw audit of all 320 attempts reported zero errors. The atomic V3 handoff
preserved all 320 completed records, all 398 queued plans, all 548 seen IDs,
coverage, and observed I/O before appending those 24 selectors. It raised the
selected-attempt cap from 320 to 512 without changing the strict effective
definition. The new controller is running in node1 tmux `hdfs_ha_rpc_v3`.

The immutable handoff intent and receipt are identical bytes with SHA-256
`00dfe55528ab5c1088c0076b2329622ca1135b5cbe1bc5eaf07d93cc246b74d7`.
The independent raw audit SHA-256 is
`5dd23bf3279974b27dd87b519fd0495f6ba75555e55cd2d8710a718a2cc7142e`.
The receipt records the predecessor and successor checkpoint SHA values and
the complete set of added selectors. These files were mirrored from node1
after the handoff; the active checkpoint continues to advance there.
