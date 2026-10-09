# HDFS-39 trial-116 exact target observation

- Original workload: released Hadoop 3.4.3 `TestFileAppend#testMultipleAppends`, one NameNode and four DataNodes. The test explicitly permits one block still in `COMMITTED` state when a file closes, then performs repeated appends and validates file contents.
- Fault plan: one `IOException` at observed `FILE_FLUSH / editLog:durable / nnlocal / ordinal 18`. The trial trace records exactly one matching and applied fault at sequence 67–68.
- Target: `FSDirAppendOp.appendFile` line 131, path `/testMultipleAppend/foo`, block 1073741825. The same block enters `COMMITTED` at sequence 71 and the exact `RetriableException(NotReplicatedYetException)` is emitted at sequence 72, after the fault. It later enters `COMPLETE`; the original JUnit exits 0.
- Source audit: `FSDirAppendOp.java` lines 130–135 intentionally throws this retriable exception while the last block is `COMMITTED`. `DFSClient.java` lines 1404–1427 retries remote `RetriableException` at 500 ms intervals for up to 5 seconds. The unchanged healthy test also exhibits the same `COMMITTED` guard and exception before recovering to `COMPLETE`.
- Same-selector replay: `replay/trial-116-1` applies the same single fault, reaches the same file/block and `COMMITTED` guard after the fault, emits the same exact exception, reaches `COMPLETE`, and exits 0.

Conclusion: reproducible target exception, **expected retry behavior**, not evidence of a new HDFS bug. Preserve this observation in the trial table; continue exploring other selectors.
