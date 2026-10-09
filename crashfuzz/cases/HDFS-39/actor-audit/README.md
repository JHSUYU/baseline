# HDFS-39 partial historical actor audit

The unchanged `TestFileAppend#testMultipleAppends` starts a MiniDFSCluster
with one NameNode and four DataNodes. The selected `FSDirAppendOp.appendFile`
check is for `/testMultipleAppend/foo`, block `1073741825`. A healthy run can
take its `RetriableException` arm while a committed block finishes replication;
that exception alone is not a new bug.

The old graph-free campaign ran 205 JUnit attempts and counted 128 fully
applied sequences that reached the selected check after the final fault. Its
logical `nn0` label does not prove a concrete RPC endpoint for every fault.
`audit_bp_rpc_subset.py` therefore re-reads each historical plan, the raw
ordered `FAULT_APPLIED` events and the selected postfault guard. It admits a
trial only when **every** fault's raw BPServiceActor heartbeat thread names
the same RPC port as the selected NameNode IPC handler. Original-JUnit healthy
calibrations and admitted trial raw manifests are also checked.

The strict subset contains **52** actor-joined trials. The other 76
historically target-retaining trials include client append or edit-log faults
without a concrete runtime endpoint or storage-owner join, so they remain
excluded. All 52 admitted original JUnits passed. One trial had two selected
`RetriableException` events, consistent with the healthy expected retry.
The 80-effective base budget is **not met**. This audit does not mark HDFS-39
complete; an actor-aware hook and more original embedded-cluster trials are
still required. The per-trial evidence and SHA-256 receipts are in
[bp-rpc-subset.json](bp-rpc-subset.json).
