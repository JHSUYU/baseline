# ZOOKEEPER-11 v2: causal precision audit during campaign

Read-only, future-only review. The v2 full campaign was still running when its completed r0000, r0001, r0002, r0003 and r0006 trial files were examined. This review does not change its configuration, instrumentation, budget or result.

## Immutable pins

| Artifact | SHA-256 |
| --- | --- |
| v2 `config.json` | `39284f0a887d3155a9e90616d913fee26e6298e9638e8d814689e89d6872ea27` |
| v2 `full.sites.json` | `257aee2ba406a68d3847e9e28ae16360456b73737e6a4f8c5ca583e3fa95da3f` |
| r0000 `result.json` / `events.jsonl.gz` | `12a19a78bcca79a2729e6b94be808246a6f331099dcf26cc9ff9d05022fedc6c` / `cd7c9accb30a84a801cef919bba6195e23a79d150781d588ff275c51637fe1c9` |
| r0001 `result.json` / `events.jsonl.gz` | `37b00cd2aba9727d163054eb8701922bb3b2b5acdb7687d89ffa7fa6905a5bb6` / `339f7a7e5f79735b523f0c86f2ab3a22632ebdc5e2cb7988b4205e48a8ded427` |
| r0002 `result.json` / `events.jsonl.gz` | `00e91da8b9dc3dd518f4819d9470901a3b42a4c14cb106cebaddaaf6630ef7da` / `4f5f5a9f225615484539139f9d54ef042bc72cfa55f02985fd674f32a25638b7` |
| r0003 `result.json` / `events.jsonl.gz` | `e6ae9813805ee819e2dee66f71363b16208deb0cf05ec39b8e03a42a4fd9b0a1` / `86fb83315b0f6aff5d986088cdccb9276f3078a95c3ed5aa2c8526d00caf5ad5` |
| r0006 `result.json` / `events.jsonl.gz` | `bb8d5b8fad22d2af70c2bcd8bc351361e6634aaa4a795ad855ad40ed2f3500ff` / `df47e84b2480b04686b557689a4decd577e14b073082153f4dc6dc968ab4ccf1` |
| patched `QuorumPeer.java` / compiled `QuorumPeer.class` | `16d7e9723d16a984c65f3a971ea24fd8fb7381311d9db711b2bbc4970daa3270` / `446279eb1dfdb4837aaf5e65f943b54a1138a068b1b83f69b5008d6b18cca717` |
| `CurrentEpochWriteFailureTest.java` | `b115c5dc305e61916eba790beefba8b5072be0b54a02d53f45027fa36d333c01` |
| pinned core `feedback.py` / agent JAR | `eec50c2dd2f6a5fd886a98c54fc5243c6d98004618d2097100a5657117f32b25` / `38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9` |

Artifact roots are `data/mallory/campaigns/ZOOKEEPER-11-epoch-full-v2/`, `Mallory/adapters/zookeeper/cases/ZOOKEEPER-11-epoch-full-v2/`, `/users/ZhenyuLi/.mallory-worktrees/zookeeper/`, and the pinned `Mallory/dispatch/releases/224e15f3a987faab681ec46278650cca80ee3bc34b75ea2f68c87b911f9928f1/`.

## Exact observations

The existing cluster JUnit `CurrentEpochWriteFailureTest#testReadCurrentEpochFromAcceptedEpochTmpFile` writes an old value to `currentEpoch` and the newer value to `currentEpoch.tmp` using `FileUtils.write`, then restarts all three peers. On restart, `QuorumPeer.start()` calls `loadDataBase()` *before* starting leader election or the peer thread. `loadDataBase()` loads the snapshot, reads `currentEpoch` through `readLongFromFile`, and evaluates the selected `currentTmp.exists()` guard only when `epochOfZxid > currentEpoch` (patched source lines 1144–1175). The test's direct file writes are outside the current agent's observed quorum-packet hooks.

In healthy r0000, the only selected target is `zk0`, epoch 2, thread 273, occurrence `zk0:2:...QuorumPeer#loadDataBase()V:root:1`. Its `readLongFromFile` door is event 684 and the exact `@1169:branch:2` check is event 685. This is a valid same-node/epoch/thread/occurrence **local temporal** witness. It is not an observed graph edge or a traced read-from relation. The same callsite's later events 686 and 687 are after the selected check. The feedback reports one `local_timeline_door`, a singleton target closure, no closure edge and zero closure coverage IDs, while its graph contains 206 RPC and 44 task edges elsewhere.

The first targeted exception, r0001 event 681, fires at `readLongFromFile` on that same `zk0` epoch-2 `loadDataBase` occurrence. It prevents the file read, and the enclosing `loadDataBase` catches `IOException` and exits its normal epoch-check sequence; the selected guard is absent (`target_lost`). This is source-consistent, not a missed target event. By contrast r0002 faults a quorum `writeRecord` on `zk1` epoch 1 at event 574, then reaches the selected check on `zk0` epoch 2 at event 725; r0003 faults `zk2` epoch 1 at event 506, then reaches `zk0` epoch 2 at event 723. r0006 similarly faults `zk1` epoch 1 at event 320 before `zk0` epoch-2 check 719. These later hits are not evidence that the faulted packet caused the local `currentEpoch` file value or the same startup occurrence.

Why the two feedback fields remain zero:

1. The configured region is only `QuorumPeer.loadDataBase`. Its first `REGION_ENTER` in each peer lifecycle has a synthetic unscoped-root parent and no observed predecessor, so backward graph reachability from the target stops at that region. No packet `SEND→RECV` or task edge enters the epoch-2 `zk0` startup/file-read occurrence. Enabling local-timeline doors qualifies event 684 for mutation but deliberately does not invent a graph edge.
2. The pinned `feedback.py` adds coverage to `closure_coverage_ids` only when the coverage event is event-time reachable from the target. In r0000 all 264 `COVERAGE_SUMMARY` events occur after selected check event 685 (first at 1153), and none carries its thread ID. One summary even names the target occurrence at event 1347, but it is too late to be a predecessor. Thus whole-program coverage can grow while target-closure coverage remains zero. The target's `TARGET_CHECK` event is not itself a `BRANCH`/`METHOD` coverage event in this computation.

## Minimal future-only option

No honest message-send/receive hook can connect a previous quorum packet to this guard merely because the test later restarts the cluster. The target is a local startup read. A general actor handoff hook at a concrete thread/task start and claim, together with a `QuorumPeer.start()` region, could document the actual restart call chain and remove synthetic-root ambiguity, provided a unique task token and named peer/epoch are observed. It would **not** prove that a prior quorum fault changed `currentEpoch`.

To test that data dependence, a distinct extension would need observed persistent-file provenance: normalize the snapshot path, record successful `currentEpoch`/`currentEpoch.tmp` write or rename with a version/content digest, and match the precise later read on the same peer after restart. This exceeds the current local-event plus packet-send/receive graph and must be labelled separately. For coverage feedback, emit execution-time region-scoped coverage before the target, rather than treating end-of-run summaries as pretarget events. Neither proposal is validated by the present full campaign; retain its natural terminal outcome and mark the causal path as unproven.
