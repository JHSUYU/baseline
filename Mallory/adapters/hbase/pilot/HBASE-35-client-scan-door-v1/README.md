# HBASE-35 client Scan door candidate

This is a source-backed healthy calibration proposal, not a fault result.
The pinned HBase 2.6.6 `ScannerCallable.openScanner()` calls
`ClientService.BlockingInterface.scan` at source line 365. Its compiled
bytecode has one `invokeinterface scan` at offset 46, mapped to line 365.
The selected existing MiniCluster test is
`TestHBaseFsckMOB#testQuarantineCorruptMobFile`; the exact target remains
`HBaseFsck$3.visit(Result)@2715:branch:10`.

In the prior strict healthy trace
`data/mallory/calibration_v27/HBASE-35/trials/r0000/events.jsonl.gz`,
client `QueueingFuture.run` claims task 421 at seq 1290, sends a
`ClientService.Scan` RPC at seq 1291, and consumes the response at
seq 1295–1297. The scanner worker publishes distinct Result tokens at
seq 1299–1303; the exact visitor target is reached at seq 1310 and later.
The existing v3 Result identity handoff makes this a plausible observed
causal path. A fresh healthy trace must show that this **specific** new
door is unique and has a time-respecting path to the selected check.

The proposed config disables generic auto I/O fault doors while retaining
HBase adapter RPC SEND/RECV tracing. It leaves the v3 Result token overlay,
selected test, target, and pinned source unchanged. No fault injection or
full campaign is authorized by this source-only proposal.

Pinned `ScannerCallable.java` SHA-256:
`ec87ebabb6fa8e3a8c1ef4123792dfd21a657aedb10b6af0b951d5f3b0e85584`.
Compiled `ScannerCallable.class` SHA-256:
`2da2c2f0e01cdba3b61b7968148b8608858e25b0205ef67b78d7100c35685c19`.
