# HDFS-39 trial-125 candidate adjudication

This is the `SocketTimeoutException` sibling of trial 118: a single exception was injected at the observed client `append` `RPC_RESPONSE` gate, ordinal 2. The gate is at the entry of `Client.getRpcResponse`. The original trial and same-selector replay both strictly apply the fault, then record the same file/block's `COMMITTED` guard and `RetriableException` on the NameNode. Both original JUnit executions exit 1.

The replay stack ends at `TestFileAppend.testMultipleAppends:425` because **the injected local `SocketTimeoutException`** propagates through `Client.getRpcResponse` and `DFSClient.callAppend`. The server's `RetriableException` is the known transient from the healthy execution; the client does not receive it on this faulted request. Released `DFSClient.callAppend` retries a received remote `RetriableException`, not this injected local timeout.

The raw oracle candidate is retained in the checkpoint and ledger, with source and replay hashes in `candidate-reviews.json`. It is **not a validated new HDFS bug**.
