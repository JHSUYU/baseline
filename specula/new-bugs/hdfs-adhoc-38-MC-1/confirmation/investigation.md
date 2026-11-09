# MC-1 investigation record (Phase 1: evidence only)

Target: `FSDirAppendOp.java:122`, `UnsupportedOperationException`, guard
`lpPolicy != null && lpPolicy.getId() == file.getStoragePolicyID()`.
Workload: `TestFileAppend#testAppendTwice`. Base commit `734dd8a67cd`.
`NN/` = `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/namenode/`.

Ordering rule (adhoc Shared Rule 2): tracker and git-history searches run only after the
reproduction verdict is settled and may set Novelty only. Sections 1-3 use pinned-tree code,
comments, docs and tests. Section 5 holds the queries.

## 1. Code audit

### Guard and its operand

- `NN/FSDirAppendOp.java:118-124`: the guard. Reached before lease recovery (`:126`), so it pre-empts
  `AlreadyBeingCreatedException`.
- `NN/INodeFile.java:592-597`: `getStoragePolicyID()` returns the own id; if that is 0 it asks the parent.
  The value is computed from the current ancestors at each call.
- `NN/INodeDirectory.java:134-141`: a directory returns its xattr id, else its parent's, else 0.
- `BlockStoragePolicySuite.java:59-65`: LAZY_PERSIST has id 15 and `copyOnCreateFile=true`.

### Writers of the effective id

- `NN/FSDirWriteFileOp.java:815-842`: at create only. Comment at `:837`: "Copy effective policy from
  ancestor directory to current file."
- `NN/FSDirAttrOp.java:443-462`, file branch: `:448-450` throws "Policy ... cannot be set after file
  creation" for a copy-on-create policy, `:457-460` throws "Existing policy ... cannot be changed after
  file creation".
- `NN/FSDirAttrOp.java:463-466`, directory branch: `setDirStoragePolicy`, with no copy-on-create check and
  no walk over existing descendants.

### Call chain

- Tag: `DistributedFileSystem.setStoragePolicy` (`:776`) -> `DFSClient` -> `NameNodeRpcServer` ->
  `FSNamesystem.setStoragePolicy` (`NN/FSNamesystem.java:2531`) -> `FSDirAttrOp.setStoragePolicy` (`:178`) ->
  `unprotectedSetStoragePolicy` (`:433`) -> directory branch.
- Append: `DistributedFileSystem.append` -> `DFSClient.callAppend` -> `NameNodeRpcServer.append`
  (`NN/NameNodeRpcServer.java:845`) -> `FSNamesystem.appendFile` (`NN/FSNamesystem.java:3041`) ->
  `FSDirAppendOp.appendFile:121-122`.
- `DFSClient.java:1444-1452` lists `UnsupportedOperationException` for unwrapping, but
  `RemoteException.java:88` calls `asSubclass(IOException.class)`, which fails for this class, and `:89-91`
  return `this`. So callers hold a `RemoteException` whose `getClassName()` is
  `java.lang.UnsupportedOperationException`. Correction: this record first assumed a bare unchecked exception
  reached the caller. The first reproduction run showed otherwise (Phase 2 attempt log).

### Reachability and caller-side gates

- `dfs.storage.policy.enabled` defaults to true.
- `dfs.storage.policy.permissions.superuser-only` defaults to false (`hdfs-default.xml:3748`), so
  `FSNamesystem.java:2518` is inactive by default.
- `FSDirAttrOp.java:186-187` requires only WRITE on the tagged path.
- No code path rejects a directory tag when existing descendants would be affected.
- `MemoryStorage.md:92`: "Administrative privileges are *not* required to set the policy".

### Trigger scenario (counterexample `spec/output/MC_hunt_s1_bfs.out`)

1. State 2 `MCStartFile("c1")`: `fs2.create(/testAppendTwice/foo)`, own id 0.
2. State 3 `MCCompleteFile("c1")`: `out.close()`.
3. State 4 `MCSetDirStoragePolicy("Root",15)`: `setStoragePolicy("/", "LAZY_PERSIST")`.
4. State 5 `MCTargetCheck("c1")`: `fs2.append(p)` (`TestFileAppend.java:337`), `targetFired=TRUE`,
   `outcome c1 = "UOE"`, `fileOwn = 0`.

### Safeguards and other readers of the same effective id

- No safeguard found between the tag and the guard.
- `NN/FSDirTruncateOp.java:97-103`: identical guard (CR-2).
- `NN/FSNamesystem.java:4683-4726`: the scrubber deletes any file with a block in the corrupt queue whose
  effective id is 15 (T-1, comparison at `:4702`). The corrupt queue comes from
  `BlockManager.java:5279-5282`. The scrubber runs by default every 300 s (`hdfs-default.xml:624`).

## 2. Developer evidence inside the pinned tree

Comments and javadoc:
- `BlockStoragePolicy.java:53-56`: "Whether the policy is inherited during file creation. If set then the
  policy cannot be changed after file creation."
- `BlockStoragePolicySuite.java:65`: "Cannot be changed on regular files, but inherited."
- `NN/FSDirWriteFileOp.java:837`: "Copy effective policy from ancestor directory to current file."

Docs:
- `MemoryStorage.md:96`: "Setting the policy on a directory causes it to take effect for all new files in
  the directory."
- `ArchivalStorage.md:84-90`: generic resolution rule: an unspecified file returns its parent's effective
  policy. It says what `getStoragePolicy` returns and does not mention append or truncate.
- `ArchivalStorage.md:51`: Lazy_Persist is "for writing blocks with single replica in memory".
- `ArchivalStorage.md:78` Note 1: the policy is useful only for single-replica blocks.
- Append and truncate denial for lazy-persist files is not documented in either page (CR-1).

Tests:
- `TestLazyPersistFiles#testAppendIsDenied` and `#testTruncateIsDenied`: file created with the lazy flag
  (`makeTestFile(path, BLOCK_SIZE, true)`).
- `TestLazyPersistFiles#testCorruptFilesAreDiscarded`: javadoc says a lazyPersist file with lost replicas
  "must be discarded by the NN, instead of being kept around as a 'corrupt' file"; the file is on RAM_DISK.
- `TestLazyPersistPolicy#testPolicyPropagation`: created with the flag.
- No in-tree test tags an ancestor after the file exists and then appends, truncates or scrubs. No test
  asserts the retroactive behaviour either way (grep of `LAZY_PERSIST` under `src/test/java`).

## 3. Reuse before rebuild

- Persistent lookup: `specula findings ... lookup --query FSDirAppendOp --query TargetSafe --query 'lazy persist'
  --query 'Cannot append to lazy persist file'` returned `[]`.
- The shared tree `/bulk/specula-adhoc/hdfs/cases/hdfs-adhoc-38/hadoop` has instrumented classes (Hook A inside
  the target method, `harness/INSTRUMENTATION.md`), so it was rejected as a reproduction artifact.
- Known-good recipe reused from `harness/logs/build.log`: `mvn -B -o test-compile -pl hadoop-hdfs-project/hadoop-hdfs`.
- `ARTIFACT=<this worktree> harness/clean.sh` restored the sources of this worktree only. `git status` was clean
  afterwards, and a fresh build succeeded (`build_pristine.log`).
- `deps/.../hadoop-common-3.6.0-SNAPSHOT.jar` reports `revision=734dd8a67cd6df56b59ff75aa43de57834a0d248`.

## 4. Pre-filter

Source is model-checking with a real counterexample, so the code-review drop does not apply. Proceed to Phase 2.

## 5. Phase 2 attempt log and settled verdict

Level 0 succeeded, so Levels 1-3 were not needed. Attempts, in order:

1. Compile error: wrong `SafeModeAction` import. Fixed.
2. First run: `RemoteException` expected to unwrap to UOE, and FsShell expected to print a stack. Both were my
   assumptions and both wrong (`RemoteException.java:88-91`; `Command.java:482-490` prints the first line only).
   The target frame still fired. Assertions corrected.
3. Second run: `t5` failed with an NPE because the file was gone after the NameNode restart. Log:
   `FSNamesystem.java:4709 Removing lazyPersist file /testAppendTwice/foo with no replicas`, 12 ms after
   `Starting services required for active state` and 2.7 s before the DataNode re-registered. Cause: one block in
   the namespace, `BlockManagerSafeMode.java:294` truncates `1 * 0.999` to threshold 0, so safe mode ends at once
   and `processMisReplicatesAsync` queues the block as corrupt before the scrubber's first pass
   (`FSNamesystem.java:4732-4733`). Split into `t5` (a second block keeps safe mode until the report) and `t10`.
4. Third run: `t5` got `EOFException` from a client that held an IPC connection to the old NameNode. Test artifact,
   unrelated to the guard. Fixed by using a fresh client after each restart.
5. Fourth run: 12/12. Two repeats: 12/12 each (`repro/MC-1.stability.txt`).

**Verdict settled at this point, before any tracker or git-history query: REPRODUCED.**

Decision on the open question (brief 6.1, CR-1): this is a defect, not documented behaviour.

- `MemoryStorage.md:96` is the page specific to this policy and limits a directory tag to new files.
- `BlockStoragePolicy.java:53-56` and `BlockStoragePolicySuite.java:65` state the policy cannot change after creation.
- `FSDirAttrOp.java:448-450` enforces that on the direct route (live in `t4`), yet the ancestor route reaches the
  same effective state with no check.
- `ArchivalStorage.md:84-90` is a generic rule on what `getStoragePolicy` returns. It never says append or truncate
  is refused.
- The file has `own=0` and DISK replicas throughout, so nothing about it is lazy.
- The same effective id makes the scrubber delete such a file (`t9`, `t10`), which no reading of the docs supports.

Rule check: the tag is the counterexample's state 4 through the public API. It writes the ancestor's xattr and
never the file's own id (`own=0` printed in every state). No reflection, no failpoint, no edit of the target
method, classes pristine.

## 6. Novelty search (run after the verdict in section 5; sets Novelty only)

Result: **NEW**. Nothing reports this mechanism at these sites. The search changed neither the reproduction nor the verdict.

### Queries, verbatim

JIRA REST `issues.apache.org/jira/rest/api/2/search`, total hits in brackets:

1. `project = HDFS AND text ~ "\"Cannot append to lazy persist file\"" ORDER BY updated DESC` [0]
2. `project = HDFS AND (summary ~ "lazy persist" OR summary ~ "lazypersist" OR summary ~ "LAZY_PERSIST") ORDER BY updated DESC` [16]
3. `project = HDFS AND text ~ "LAZY_PERSIST" AND text ~ "append" ORDER BY updated DESC` [8]
4. `project = HDFS AND text ~ "LazyPersistFileScrubber" ORDER BY updated DESC` [24]
5. `project = HDFS AND text ~ "copyOnCreateFile" ORDER BY updated DESC` [2]
6. `project = HDFS AND text ~ "LAZY_PERSIST" AND text ~ "setStoragePolicy" AND text ~ "directory" ORDER BY updated DESC` [2]
7. `project = HDFS AND text ~ "\"lazy persist\"" AND text ~ "existing files" ORDER BY updated DESC` [11]
8. `project = HDFS AND text ~ "\"Removing lazyPersist file\"" ORDER BY updated DESC` [3]
9. `project in (HDFS, HADOOP) AND text ~ "\"Cannot truncate lazy persist file\""` [0]
10. `project = HDFS AND text ~ "\"lazy persist\"" AND text ~ "inherit" ORDER BY updated DESC` [5]
11. `project = HDFS AND text ~ "LAZY_PERSIST" AND text ~ "\"parent directory\"" ORDER BY updated DESC` [1]
12. `project = HDFS AND text ~ "LAZY_PERSIST" AND text ~ "ancestor" ORDER BY updated DESC` [1]
13. `project = HDFS AND text ~ "lazy_persist" AND text ~ "retroactive" ORDER BY updated DESC` [0]
14. `project = HDFS AND text ~ "\"storage policy\"" AND text ~ "\"cannot append\"" ORDER BY updated DESC` [1]
15. `project = HDFS AND text ~ "LAZY_PERSIST" AND created >= 2025-01-01 ORDER BY created DESC` [0]
16. `project = HDFS AND text ~ "LAZY_PERSIST" AND text ~ "rename" ORDER BY updated DESC` [9]

GitHub `api.github.com/search/issues`, all states, sorted by updated (covers open, merged and closed PRs):

17. `repo:apache/hadoop is:pr "lazy persist" append` [0]
18. `repo:apache/hadoop is:pr LAZY_PERSIST` [2: #8637, #4367]
19. `repo:apache/hadoop is:pr FSDirAppendOp` [1: #5583]
20. `repo:apache/hadoop is:pr LazyPersistFileScrubber` [1: #2408]
21. `repo:apache/hadoop is:pr copyOnCreate` [0]
22. `repo:apache/hadoop is:pr "storage policy" lazy directory` [2: #8347, #2408]
23. `repo:apache/hadoop is:pr lazypersist scrubber` [0]
24. `repo:apache/hadoop is:pr getLocalStoragePolicyID` [1: #3898]

Git, no checkout (`refs/remotes/origin/trunk`, tip `f8422975702`, 2026-10-26):

25. `git log trunk --not HEAD -- <FSDirAppendOp FSDirTruncateOp FSDirAttrOp INodeFile INodeDirectory FSDirWriteFileOp BlockStoragePolicy BlockStoragePolicySuite>`: none.
26. `git log trunk --not HEAD -i -E --grep='lazy.?persist|storage.?polic'`: none.
27. Sanity check on that range: 169 commits, 10 touching `namenode/`. The only site among them is `FSNamesystem.java`, by HDFS-17980, HADOOP-19951 and HDFS-17924, none about this.
28. `git log HEAD -i -E --grep='lazy.?persist'`: 30 commits, 2014-2020. None is about directory tags reaching existing files.
29. `git log HEAD -8 -- FSDirAppendOp.java`: refactors and EC append changes.
30. `git log -S'Cannot append to lazy persist file'` and four more pickaxes: **stopped, no result** (see Side effect).

Other:

31. Web: `HDFS LAZY_PERSIST storage policy set on directory existing files append "Cannot append to lazy persist file" bug`: no bug report found.
32. Web: `HDFS LazyPersistFileScrubber deletes non lazy persist file inherited storage policy parent directory data loss JIRA`: no matching issue found.
33. Specula dataset: `specula-org/specula-case-studies` tree (28561 entries), paths matching `hdfs|hadoop|namenode|lazy`: only an unrelated nvflare file. The local `case-studies/` directory is empty.
34. `specula findings lookup` (section 3): `[]`.

### Near matches read and rejected

- HDFS-8229 (Fixed in 2.8.0, 3.0.0-alpha1), "LAZY_PERSIST file gets deleted after NameNode restart": same scrubber, different mechanism. It concerns files created lazy, and its fix is the safe-mode check at `FSNamesystem.java:4732`. Related precedent for `t10` only: with one block in the namespace that check does not hold the scrubber back.
- HDFS-14947 (Open), "infrequent data loss due to rename functionality breaking": no mechanism identified; it matched on generic words. Not this.
- HDFS-13085 (REST vs CLI output), HDFS-16428 (rename quota), HDFS-13672 and HDFS-15354 (scrubber lock time): other defects.
- HDFS-7159, HDFS-7634, HDFS-7643, HDFS-6929, HDFS-8495: feature and refactor issues that introduced these sites, not reports of this defect.

### Developer statements found by the search (context only, after the verdict)

- HDFS-7159 description: "An additional advantage is that can support setting the lazy persist preference on a directory and it will take effect for all new files."
- HDFS-7159 comment, arp, 2014-09-28: "If set, then the policy is inherited by the file on creation and cannot be reset later."
- HDFS-7634 description, quoting the HDFS-6581 design doc: "Appends to files created with the LAZY_PERSISTflag will not be allowed in the initial implementation to avoid the complexity of keeping in-memory and on-disk replicas in sync on a given DataNode."
- HDFS-6929 description: "Occasional data loss is expected when using the lazy persist flag due to node restarts."

### Side effect of query 30

The clone is partial (`remote.origin.promisor=true`, `partialclonefilter=blob:none`), which I did not check first. The pickaxe lazily fetched blobs into the shared `.git`, and each fetch started `git gc --auto`. I stopped the job once I saw this.

- Pack mtimes in the shared object store: 23 packs in total, 23 dated inside the job window (06:57-07:02), 0 before it, 0 after it. That includes the 235 MB main pack at 07:00, so an auto-gc triggered by these fetches repacked the store. Reachable objects are preserved by that, and the checks below passed. A concurrent worker can also touch these files, so this count is not an exact measure of what my job added.
- `tmp_pack_nGIgfN` and `tmp_idx_nqubsM` (07:01:20, about 1 KB each) match the time of the stop, so they are probably from my killed fetch. Left in place; `git gc` removes them. Two other temp files dated 06:51:13 predate the job and are not mine.
- Checked afterwards: base commit and the target's HEAD blob present, `git fsck --connectivity-only HEAD` silent, shared tree status unchanged (9 entries), no git process left in this case.
