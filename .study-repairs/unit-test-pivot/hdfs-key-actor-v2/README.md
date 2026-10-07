# HDFS-11/12 actor-aware V2 follow-up

This is a new, isolated graph-free overlay for the unchanged Hadoop 3.4.3
`TestEncryptedTransfer` parameterized JUnit child `[0]` (normal encrypted
transfer, `resolverClazz == null`). It does not rewrite the original test,
GraphChecker, the shared fuzzer, or archived HDFS-11/12 results. The old
campaigns are historical evidence; this directory owns new receipts and
checkpoints.

## Exact source and actor mapping

| Event | Hadoop 3.4.3 source | V2 identity |
| --- | --- | --- |
| Cluster/DN creation | `MiniDFSCluster.startDataNodes` deepest overload, around line 1666; `DataNode` constructor before `startDataNode`, around line 593 | One startup episode plus DN slot and normalized configured `dfs/data/dataN` directories. The second MiniDFSCluster in one original JUnit is another episode. |
| DN key manager | `DataNode.registerBlockPoolWithSecretManager`, around lines 2111–2141 | The actual `BlockTokenSecretManager` object is bound to that DN when `addBlockPool(blockPoolId, secretMgr)` is called. Its raw block-pool ID is retained; `BP0` is the stable per-actor label. |
| DN SASL receiver | `DataNode.startDataNode`, around line 1962 | The actual `saslServer` object is bound to the same DN before any server read. Raw `Peer` local/remote endpoints are recorded. |
| Fault points | `SaslDataTransferServer.doSaslHandshake`, around lines 374, 384 and 404 | The exact read call sites (`readMagic`, `readSecret`, `readOptions`) get receiver actor, unique pool label, and actor-local ordinal. An unbound or multi-pool receiver cannot inject. |
| HDFS-11 target | `BlockTokenSecretManager.retrieveDataEncryptionKey`, Map.get line 551, null guard 552, selected throw 553 | Exact `TARGET_CHECK` and `TARGET_THROW` carry the manager's bound DN and pool. Original selector line 555 was in the exception message. |
| HDFS-12 target | `BlockTokenSecretManager.retrievePassword`, Map.get line 509, null guard 511, selected throw 514 in released bytecode/source continuation | Same manager-bound identity; the unrelated earlier expired-token throw is not the selected oracle. |

The current V2 relation is **same receiver DataNode and same block pool**.
This permits a SASL read fault to precede a later target check on that receiver;
it does not claim a proven key-update causal edge, nor does it mix a later
target on another DN or cluster incarnation. Raw peer endpoints are evidence,
not stripped into a false common endpoint. The selector uses the actual
receiver object mapping plus an actor-local ordinal; if two seeds show
different full selectors, calibration fails instead of widening the match.
Producer-side NameNode-to-DataNode key RPCs are outside this first V2 fault
scope and would require an explicit response/command relation.

## Offline checks and host-slot commands

The Python gate fixtures need no JVM:

```sh
cd /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/hdfs-key-actor-v2
python3 -m unittest -q test_identity_gate.py
python3 test_scheduler.py
python3 -m py_compile run_original.py identity_gate.py campaign.py
```

**Wait for a free JVM/cluster host slot before the following commands.** Each
calibration uses two fresh executions of the named original JUnit child. The
first command can pause after healthy `a`; the second reuses it and runs
healthy `b`. Keep each case's output directory on one host.

```sh
cd /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/hdfs-key-actor-v2
python3 identity_gate.py calibrate --case HDFS-11 --output evidence/HDFS-11 --max-seeds 1
python3 identity_gate.py calibrate --case HDFS-11 --output evidence/HDFS-11 --max-seeds 2
python3 identity_gate.py calibrate --case HDFS-12 --output evidence/HDFS-12 --max-seeds 1
python3 identity_gate.py calibrate --case HDFS-12 --output evidence/HDFS-12 --max-seeds 2
```

HDFS-11 default JUnit: `TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[0]`.
HDFS-12 default JUnit: `TestEncryptedTransfer#testLongLivedClient[0]`, which
uses short key lifetime and 15 seconds of key rotation. For an additional
HDFS-11 expired-key workload, use `--method testFileChecksumWithInvalidEncryptionKey`
with a **separate** output directory, never combine its healthy baseline with
the default test. That original test expects/retries an invalid encryption
key; its healthy selected-throw count must be preserved in the oracle.

The receipt requires both original JUnits to pass, exact target and upstream
I/O to have a bound same-actor/same-pool pair, matching overlay digests,
stable target actor/pool sets and at least one stable full selector. A failed
receipt blocks fault trials. `-Xverify:all` checks woven classes when JUnit
runs. The released Hadoop classes, original JUnit child and JaCoCo production
coverage remain the workload/feedback.

After a passing two-seed receipt, run each case as a separate tmux session:

```sh
tmux new-session -d -s hdfs11_key_v2_fuzz 'cd /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/hdfs-key-actor-v2 && python3 campaign.py --case HDFS-11 --output evidence/HDFS-11 --max-attempts 600 --pause-on-candidate >> evidence/HDFS-11/campaign.log 2>&1'
tmux new-session -d -s hdfs12_key_v2_fuzz 'cd /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/hdfs-key-actor-v2 && python3 campaign.py --case HDFS-12 --output evidence/HDFS-12 --max-attempts 600 --pause-on-candidate >> evidence/HDFS-12/campaign.log 2>&1'
```

Do not start both on one host unless its coordinator has two cluster slots.
The case-local `campaign-state.json` is written atomically before and after
each attempt. Repeating the same command resumes pending work and never
reruns a completed sequence; a trace without a manifest is an incomplete
attempt and may be retried in its own V2 run directory. Each run has a
manifest, trace, JaCoCo files, exact plan, elapsed time, and `v2_result.json`.
Budget: 80 effective same-actor postfault trials, at most 8 faults/sequence;
extend to 128/10 only if the last eight effective trials add production
coverage or a new eligible I/O family. `--max-attempts` is a safety cap.

For a single planned trial, the six TSV columns are
`marker, siteId, faultActor, resource, actorLocalOrdinal, exceptionType`.
The strict gate requires all requested markers applied in order and an exact
target check **after** the last fault on the same actor/pool. A matching
target exception above the healthy count is a candidate for replay and source
review, not a confirmed bug. Coverage and I/O mutations use only valid
target-retaining trials. The HDFS-11 node1 scheduler migration at
`evidence/HDFS-11/scheduler-migration/migration-receipt.json` preserves the
old queue and runner hashes. After at least three strictly applied trials in
one multi-fault suffix lose the same-actor target, with no valid trial in that
suffix, the scheduler lowers its priority. A target-retaining trial removes
that penalty. Every twelfth choice can still explore a demoted suffix, and
new code/I/O coverage remains in the priority score. The exact fault gate
and effective budget are unchanged.

## Current status

HDFS-11 passed two fresh original JUnit healthy calibrations on node1:
17.481 and 17.807 seconds, exit 0, stable same-DN/BP target and six eligible
SASL selectors. Its isolated campaign runs in tmux `hdfs11_key_v2_fuzz` and
resumes from the atomic case checkpoint. The 2026-10-07 04:57:51 UTC
scheduler handoff recorded 43 completed trials, 25 effective trials, and a
finished JUnit manifest for the next in-flight plan; restart consumed that
manifest without rerunning the JUnit. HDFS-12 has not yet started a V2 JUnit
on node1 and remains separate from the HDFS-11 campaign.
