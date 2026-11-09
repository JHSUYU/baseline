# hdfs-adhoc-38: Existing non-lazy-persist files inherit LAZY_PERSIST from a parent directory set later (or after a rename), which makes them permanently un-appendable and lets the LazyPersistFileScrubber delete durable DISK files whose replicas are temporarily unavailable.

Severity (reviewer): **data-loss**

## The ad hoc check (the prompt's only target)

- `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/namenode/FSDirAppendOp.java:122`, `FSDirAppendOp.appendFile(FSNamesystem, String, FSPermissionChecker, String, String, boolean, boolean)`, throws `java.lang.UnsupportedOperationException` when `lpPolicy != null && lpPolicy.getId() == file.getStoragePolicyID()`
- Starting test: `org.apache.hadoop.hdfs.TestFileAppend#testAppendTwice`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** Ordinary client/admin operations. A file is created without LAZY_PERSIST and written to DISK. Then setStoragePolicy(parentDir, LAZY_PERSIST) is called, or the file is renamed into a LAZY_PERSIST directory, and the file is appended.

**Why (root cause in the source):** LAZY_PERSIST is copy-on-create. FSDirWriteFileOp.setNewINodeStoragePolicy fixes it on the inode at create time (namenode/FSDirWriteFileOp.java:815-841), and FSDirAttrOp forbids setting it on an existing file (namenode/FSDirAttrOp.java:446-451). MemoryStorage.md:96 documents that setting it on a directory 'take[s] effect for all new files in the directory'. However, INodeFile.getStoragePolicyID falls back to the parent's policy when the local policy is unspecified (namenode/INodeFile.java:592-597). As a result, existing DISK-resident files are treated as lazy-persist: append (and truncate) is rejected for good at FSDirAppendOp.java:121-123. Worse, LazyPersistFileScrubber.clearCorruptLazyPersistFiles uses the same inherited id (namenode/FSNamesystem.java, clearCorruptLazyPersistFiles: bc.getStoragePolicyID()==lpPolicy.getId()) and deletes such a durable file from the namespace whenever its replicas are briefly missing. The agent's third test demonstrates this deletion: the DN is stopped, the NN restarts and leaves safe mode, and the file is deleted even though the DN's replica is intact. The user never asked for these files to become lazy-persist.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** LAZY_PERSIST is a copy-on-create policy (isCopyOnCreateFile): the design fixes it on a file only at create time (FSDirWriteFileOp.setNewINodeStoragePolicy copies it from the ancestor into the inode) and FSDirAttrOp.unprotectedSetStoragePolicy explicitly forbids putting it on an existing file. The append/truncate check and the scrubber rely on that invariant: 'policy is LAZY_PERSIST' is supposed to mean the file was written as a lazy-persist (RAM_DISK, possibly not durable) file. Inheritance through INodeFile.getStoragePolicyID() lets a directory-level setStoragePolicy, or a rename into such a directory, make existing files that were written normally on DISK look lazy-persist after the fact. This breaks the copy-on-create protocol, a state the coordination between create and setStoragePolicy should never produce. The user did not ask for an invalid operation: the file was created without LAZY_PERSIST and the direct attempt to make it lazy-persist is rejected. In a real deployment, an admin marking a scratch or temp directory LAZY_PERSIST for new files (or a job moving output into it) makes every existing file under it permanently impossible to append to or truncate (it survives NN restart because nothing changes in the file), so HBase WALs, log appenders and Flume sinks start failing. Worse, the LazyPersistFileScrubber treats those durable DISK files as disposable: whenever their replicas are briefly unavailable (DataNode restart, NN restart before block reports, rack outage), it permanently deletes them from the namespace. That is silent data loss of data that was fully persisted.

**Execution (agent):** MiniDFSCluster with 1 NameNode and 1 DataNode, default config (storage policies enabled). (1) A client (writer, non-superuser) creates /data/log WITHOUT the LAZY_PERSIST flag, writes half a block and hflushes; the NN sets no local policy on the inode (/data has none) and the replica goes on DISK. (2) While the file is still open, an administrator running at the same time calls setStoragePolicy(/data, LAZY_PERSIST). The same call on /data/log itself is rejected ('Policy LAZY_PERSIST cannot be set after file creation'), but on the directory it succeeds, because only an xattr on the directory is written. (3) The writer finishes and closes the file normally; all replicas are on DISK and the inode's local policy is still UNSPECIFIED, yet getStoragePolicy(/data/log) now reports LAZY_PERSIST because INodeFile.getStoragePolicyID() falls back to the parent. (4) The writer calls append(/data/log); FSDirAppendOp.appendFile sees file.getStoragePolicyID()==LAZY_PERSIST and throws UnsupportedOperationException('Cannot append to lazy persist file /data/log') at FSDirAppendOp.java:122, which reaches the client as RemoteException(java.lang.UnsupportedOperationException). Same outcome with no concurrency: testAppendRejectedAfterRenameIntoLazyPersistDir renames an ordinary, already-appended file into a LAZY_PERSIST directory and the next append fails at the same line. testInheritedLazyPersistFileDeletedByScrubber shows the consequence: after setStoragePolicy(/data, LAZY_PERSIST), the DataNode holding the only replica stops, the NN restarts and leaves safe mode, and FSNamesystem.LazyPersistFileScrubber (which uses the same inherited getStoragePolicyID()) logs 'Removing lazyPersist file /data/log with no replicas' and deletes the ordinary DISK file; when the DataNode returns with its intact replica, the file is gone.

**Stack frame (agent):** at org.apache.hadoop.hdfs.server.namenode.FSDirAppendOp.appendFile(FSDirAppendOp.java:122)

## Reproduction

- Test: `org.apache.hadoop.hdfs.TestAppendLazyPersistInheritance#testAppendRejectedAfterParentSetToLazyPersist`
- Command: `mvn -B -o test -pl hadoop-hdfs-project/hadoop-hdfs -Dtest='org.apache.hadoop.hdfs.TestAppendLazyPersistInheritance#testAppendRejectedAfterParentSetToLazyPersist' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/TestAppendLazyPersistInheritance.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `java.lang.UnsupportedOperationException: Cannot append to lazy persist file /data/log`, frame `at org.apache.hadoop.hdfs.server.namenode.FSDirAppendOp.appendFile(FSDirAppendOp.java:122)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h07m | 1 | 865,782 | 44 | 18,817 | 52,572 | 794,349 | $0.96 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
