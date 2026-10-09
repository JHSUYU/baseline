# HDFS-39 trial-180 four-fault candidate adjudication

The original trial and same-selector replay strictly applied four ordered faults: two DataNode block-report response `IOException`s, one DataNode block-report pre-send `IOException`, then a client `append` response-wait `SocketTimeoutException`. Both executions reached the same `/testMultipleAppend/foo` block 1073741825 in `COMMITTED` state after the final fault, emitted the exact target `RetriableException`, and exited 1. The JUnit failure stack in both points to **the fourth locally injected timeout** at `Client.getRpcResponse` → `fs.append` → `TestFileAppend.java:425`.

The strict first-three-fault ablation is decisive: all three DataNode faults apply, the same block enters `COMMITTED` and emits the exact target exception **twice after the final DataNode fault**, then reaches `COMPLETE`; the unchanged JUnit exits 0. This directly observes `DFSClient.callAppend`'s documented retry behavior under the three DataNode faults. The fourth local timeout interrupts receipt of the remote response and causes the failing run to terminate. The target exception is a recoverable transient, not the cause of the operation failure.

Keep the original candidate and replay evidence in the ledger and `candidate-reviews.json`; **no new HDFS bug is validated**.
