# HDFS-08 r0067: source mechanism and door feasibility

Read-only follow-up to [the pinned trace audit](HDFS-08-r0067.md). No JVM was run. This review asks whether the two exact `IOException` injections can affect the selected `Journal.checkRequest` epoch comparison, and whether the existing trace offers a target-retaining precheck I/O door.

## Source pins and selected condition

The campaign configuration pins Hadoop 3.4.3 `Journal.java` to SHA-256 `be5c67ce7564ad67b9b464d93956f0e855dd76df1253958412947c1abb2fd6f3`. Additional reviewed source in `/users/ZhenyuLi/.mallory-worktrees/hdfs` is:

| Source | SHA-256 | Relevant lines |
| --- | --- | --- |
| `hadoop-common/.../ipc/Server.java` | `786720814e5c295d7e5c549928653793058d8466ab259e755a` | 1235–1264 |
| `hadoop-hdfs/.../qjournal/client/QuorumJournalManager.java` | `a1384d41147c71c3d399bfb33a6c943bfe79ad1fbe74cbc91a95a6fb4c1d8f64` | 227–248, 474–479 |
| `hadoop-hdfs/.../qjournal/client/IPCLoggerChannel.java` | `8e85f42f96f6300cc28fd4bf73f7c172518caae804da6a1483d7a579f5b1c035` | 184–185, 287–290 |
| `hadoop-hdfs/.../qjournal/protocol/RequestInfo.java` | `202a794ca427d213cfd83f4aaa90f790099b23d2bfec522698db513e8cff061f` | 45–50 |
| `hadoop-hdfs/.../hdfs/util/PersistentLongFile.java` | `dd8da43c5efbd80c62df3ff4f4cdad631064b479b892dcc6a68f1379e68296c8` | 53–66, 76–87 |

`Journal.checkRequest` line 486 compares `reqInfo.getEpoch()` with the local `lastPromisedEpoch.get()`. The request epoch is created from the `IPCLoggerChannel` epoch; `QuorumJournalManager.createNewUniqueEpoch` first obtains `getJournalState` responses, chooses `max(lastPromisedEpoch)+1`, then sends `newEpoch` to a write quorum. On each JournalNode, `Journal.newEpoch` lines 339–375 calls `updateLastPromisedEpoch`, which writes the promise using `PersistentLongFile.set`. `Journal.checkRequest` can also increase that promise at lines 490–493, **after** evaluating the selected lower-epoch predicate. In general, an exception in an earlier request could prevent such an update if that request carried a newer epoch. The concrete r0067 faulted requests occur after the corresponding `newEpoch` updates and have no observed epoch-changing continuation; they can affect other recovery behavior without demonstrating a change to this selected predicate.

## What r0067 actually does

The healthy trace `r0000/events.jsonl.gz` is SHA-256 `c51aee26578841d0d0f5534f0157c226276af9e1ef085a2e8c080264f6e3783c`, and its result is `a2a2bebff4057171929b6ed6a97a7745c6122e8d622cec1219bf5526fc454e05`. It identifies the `jn0` RPC context 21 as `Journal.journal` followed by `checkWriteRequest` and the selected `checkRequest`. In r0067, the exact same runtime point receives fault `:833`; no `Journal.journal` or `checkRequest` executes in that occurrence. `Server.RpcCall.run` catches the thrown exception at line 1248 and sends an error response. The target later on `jn0` is finalization in a separate context 38 (`:1554`→`:1561`).

The r0067 trace records `updateLastPromisedEpoch` on all three JournalNodes before the first fault (`:596`, `:634`, `:672`) and again before the second fault (`:1057`, `:1084`, `:1097`). The second fault `:1469` is on `jn2` context 36; the next target checks are `jn1` context 37 and `jn0` context 38. The fault suppresses its own request. The trace carries no numeric epoch values, so this is a source-and-order exclusion for these injected sites, not proof that every possible epoch-failure scenario is impossible.

## Existing pretarget doors

The faulted trial has 48 observed doors. Its two target-closure doors are `jn1 :1488` (context 37) and `jn0 :1552` (context 38), both `Server$RpcCall.run@1246` immediately before the business RPC. Injecting at either door would throw before `Journal.finalizeLogSegment` calls `checkRequest` (Journal lines 629–632), so it cannot retain that same target occurrence. Nine observed `Journal.persistPaxosData@1109/1110/1111` file-write doors occur in earlier contexts 33–35; they write recovery Paxos data (Journal lines 1095–1120), not the promise file used by line 486. There is no observed door on `lastPromisedEpoch.set/get` in this campaign; `state.fields=false`, and the promise is already accessed before these faults.

The original faulted trace lacks a same-occurrence target-retaining door whose exception can change the selected epoch comparison. Adding numeric thread IDs would improve actor identity, but contexts 21, 36, 37, and 38 are already distinct and the source control flow would still skip the target after an `RpcCall.run` exception. **Do not spend a bounded numeric-thread rerun on this r0067 door family.** A different experiment would first need an explicit promise-write or `getJournalState` response mechanism, typed request/response identity, epoch value observations, and a source-justified postfault target path; it would be a new campaign design rather than an upgrade of this terminal trace. A true stale writer is intentionally fenced by line 486, so reaching its exception alone would still need operation-level review before being called a bug. Keep HDFS-08 `faulted_path_unverified`.
