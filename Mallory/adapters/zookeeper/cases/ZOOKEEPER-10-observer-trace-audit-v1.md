# ZOOKEEPER-10: source and trace audit (read only)

This audit concerns the completed `ObserverMasterTest#testObserver` campaign. It does not change the terminal result or claim a new bug.

## Pinned evidence

| Artifact | SHA-256 |
| --- | --- |
| `data/mallory/campaigns/ZOOKEEPER-10-observer-full-v1/result.json` | `3c222c3925bce5838a1721b0928b265891b8bdb646d5af12ccb60a532599d2a8` |
| `data/mallory/campaigns/ZOOKEEPER-10-observer-full-v1/offline-causal-audit.json` | `a7006a3b9757fa9972482f38d4f16933768ab7446349594878e0c3c2db94fe28` |
| `trials/r0000/events.jsonl.gz` under that campaign | `15cb4453c8f77fdc3e3ff3a648ba20709adbc0feac5e1d0b9bda9dd524b091e6` |
| `trials/r0009/events.jsonl.gz` | `ec1a3e6fc2f588731e801049a1504a1b9faccf01d2ea634e62f0a4aad39efef8` |
| `ObserverMaster.java` in pinned ZooKeeper worktree | `d4f7ad587bbbd6a105e929fa9b52694a73ea678d59b03eac530f9bf0184506f6` |
| `Follower.java` in pinned ZooKeeper worktree | `3ab87632c5c633d1c74ba0fddf52550c78918cf4015ea51350a0af0fac4c7db8` |
| `MalloryZkHooks.java` in pinned ZooKeeper worktree | `5185ee55bfd8f86bead9924b2ca2cbe275b407995591ce289f2b8d2d3d9a22fa` |
| `full.sites.json` | `59ef59cefd9f564428a1b33a44f496a2dcdbba425740d9db00083eab905a5abb` |

## Observed path and its limit

The healthy r0000 trace proves a physical packet path to the selected guard. The leader's `zk2` `writeRecord` door at seq 92 precedes the `COMMIT` send at seq 94, correlation `127.0.0.1:11223>127.0.0.1:36396#6:4:4294967297`. The same correlation is received on `zk1` at seq 95, after its read door at seq 88. `Follower.processPacket` enters at seq 96, `ObserverMaster.proposalCommitted` at seq 97, `removeProposedPacket` at seq 98, and the exact check `@368:branch:3` executes at seq 99, all on named `zk1`, epoch 0, thread 33. The earlier `PROPOSAL` packet for zxid 4294967297 is received at seq 83 and enqueued by `proposalReceived` at seq 85. The offline audit reports 13 healthy named doors with observed paths.

The selected predicate compares the head of `ObserverMaster.proposedPkts` against the committed `zxid`. In pinned source, `proposalReceived` queues the proposal at lines 358–360; `proposalCommitted` calls `removeProposedPacket` at lines 410–411; the target comparison and throw are at lines 368–374. `Follower.processPacket` calls those methods from its `PROPOSAL` and `COMMIT` cases at lines 198 and 207. There is no I/O call between `proposalCommitted` and the target comparison, or between the queue peek and that comparison.

The current doors are *not packet-typed at injection time*. `MalloryZkHooks.Input.readRecord` calls `beforeDoor` before `super.readRecord` and only emits `RECV` after successful deserialization; `Output.writeRecord` calls `beforeDoor` before `super.writeRecord` and only emits `SEND` after successful serialization. Its `DOOR_OBSERVED` event records `readRecord` or `writeRecord`, node and ordinal, but no packet type or zxid. A fault at either door prevents the faulted packet's own post-I/O `SEND` or `RECV` event. A healthy observed path therefore does not prove a postfault path for that same packet.

The full campaign naturally completed 80 fault trials, all strictly applied; 48 trials reached the target somewhere afterward and none reached the selected throw. The offline audit finds zero same affected actor/occurrence target continuations. Of 80 faults, 25 were `zk1` epoch-0 read doors, 18 `zk1` epoch-0 write doors, and the remaining 37 were other node/epoch read or write doors. Thirteen trials were initially selected by dynamic closure; the remaining 67 were bounded outside-closure exploration. No fault trial increased target-closure coverage. In r0009, a `zk1` epoch-0 read fault at seq 90/thread 33 is followed by a target check only at seq 541 on `zk1` epoch 1. In r0008, a `zk2` epoch-0 write fault at seq 94 is followed by a check on `zk1` epoch 1 at seq 526. These are later recovery executions, not continuations of the interrupted packet path. Across all 80 trials, 48 had any later target, 26 had one on the same node, seven on the same node and epoch, and zero on the same node, epoch and thread as the fault. Same-node counts alone also do not establish same packet or zxid.

## Minimal future precision plan

If a new version is justified, keep this terminal campaign immutable. In an isolated adapter, qualify `QuorumPacket` doors by packet type (`PROPOSAL=2`, `COMMIT=4`), zxid, sender/receiver and socket ordinal. On writes, the packet object is available before `beforeDoor`; on reads, the type is only known after deserialization, so any post-read injection location and its exception behavior require separate source review. First run one healthy existing cluster JUnit and verify a unique `PROPOSAL` enqueue and matching `COMMIT` receive by zxid, with the exact target on the receiving follower. Then run one bounded fault trial and require an observed postfault packet or queue handoff into the exact target on the appropriate named actor/epoch. A later target on a different packet, thread or epoch is an outcome, not that handoff. Do not promote a new full campaign from the present generic read/write door trace alone.

No existing source location was found where a caught injected `IOException` between the `COMMIT` receive and selected comparison preserves that same packet's target execution. A type-qualified door would improve selection and diagnosis; its ability to change the selected predicate remains unproven.
