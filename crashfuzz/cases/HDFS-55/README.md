# HDFS-55: Balancer cached encryption-key coordination check

This supplements the original 102-site selection with the known HDFS-17899
check in Hadoop 3.4.3. The target is
`KeyManager.newDataEncryptionKey()` at `KeyManager.java:123`: the Balancer
reuses a locally unexpired cached key even when the destination DataNode no
longer accepts its key ID. The check spans NameNode-issued block keys,
Balancer cache state, and the remote DataNode SASL result. The original
embedded-cluster workload is the unmodified
`TestBalancerWithEncryptedTransfer#testEncryptedBalancer0` JUnit.

The evidence has two workload layers. The unchanged original JUnit supplied
44 site-level fault attempts: one initial stateful control, 31 exact-plan
trials, and 12 runtime-prefix trials. Thirty-one of these fully applied a
fault, and 27 reached this target after the final fault. These runs establish
site reachability and coverage; they do not by themselves reproduce the
known issue. The causal HDFS-17899 differential used a **case-local adapted**
encrypted one-node phase via the original `TestBalancer.integrationTest` /
`oneNodeTest` helper, with one Balancer mover thread and a 180-second JUnit
bound. Its two original-version faulted runs (first run and clean replay)
applied the same persistent DataNode rejection model, reached the cached-key
guard, failed the Balancer operation, and differed from the minimal fixed
run. The checklist's 46 fault trials, 33 fully applied trials, 29 postfault
target reaches and 2831.325 seconds aggregate these layers. The known-bug
mark belongs to the adapted differential; it is not a claim that the
unchanged JUnit directly reproduced HDFS-17899.

`build_overlay.py` instruments the exact KeyManager guard without changing
its boolean result and the outbound Balancer SASL call. Every event logs
the Balancer manager identity, cached key ID, target DataNode, guard result,
and whether it happened after a matched fault. The first control uses a
stateful exception policy: it throws `InvalidEncryptionKeyException` on
outbound SASL attempts starting at a selected attempt, up to a cap. Its
**first** injected attempt used a newly fetched key (`KeyManager` guard
`refresh=true`, cached key absent). Thus that synthetic control calibrates
the missing clear/retry response but does not alone establish HDFS-17899
at a previously cached key. The separate exact-plan campaign injects only
at selected outbound SASL ordinals for which the same Balancer
`KeyManager`, key ID, and `refresh=false` guard are observed at runtime.
The sequence is selected from the original JUnit's I/O trace and coverage
feedback; no Docker cluster or causal graph is used.

The operation oracle is the original JUnit's Balancer block-move result and
exit status, supported by the repeated same-key guard outcome. A failed
injected I/O call by itself is insufficient. `jacoco.exec` and derived
covered method/branch files capture code coverage. Each trial writes its
own `manifest.json`, log, raw coverage, and a resumable campaign checkpoint.
The independent known-bug control lives at
`../../known-bug-controls/HDFS-17899/` and has already shown original 3.4.3
failure versus a minimal clear-and-retry fix. This site-level campaign
checks whether the new target guard is actually reached after a fault.
In the tagged 3.4.3 source, `TestBalancer.testBalancer0Internal` invokes
`oneNodeTest` and `twoNodeTest`; `TestBalancer.runBalancer` checks the
Balancer exit code against `ExitStatus.SUCCESS` at `TestBalancer.java:825`.
`Dispatcher.PendingMove.dispatch` records a successful block move only
after `sendRequest` and `receiveResponse` complete. Its generic
`IOException` catch at `Dispatcher.java:408` marks the move failed without
clearing the Balancer encryption-key cache. Those are the source-side
operation and error-handling outcomes used to review a failure candidate.

## First site-level differential

The healthy original JUnit passed with 15 successful block moves. Its
KeyManager check executed 30 times and the outbound Balancer SASL site
executed 15 times. Under the stateful exception policy, original 3.4.3
injected at all 18 observed Balancer SASL attempts, never cleared the cached
key, and moved no blocks; the original JUnit failed. After the first fault,
the exact KeyManager check ran 17 more times and each time reused the cached
key (`refresh=false`). These 17 events had the same key ID; the remote
DataNode address and manager identity are in the raw log. The minimal
HDFS-17899 fix control, with the same fault policy and JUnit, cleared the
key twice, retried, moved all 15 blocks, and passed. The two clears reflect
two Balancer cluster phases in the original JUnit.

The original fault run added 193 Hadoop JaCoCo probe IDs and 48 covered
production methods over the healthy seed after excluding the case-local
probe helper. The raw `.exec` files and derived coverage lists are retained
per run. This differential confirms a response to a synthetic fault at this
added check. An exact cached-key failure and paired fixed replay are needed
for full reproduction of the *known* HDFS-17899 failure. It is not a new bug.

## Exact-plan campaign

`campaign/campaign.py` keeps an atomic `state.json` checkpoint and a trial
ledger. Each plan contains one or more observed outbound SASL ordinals, the
`balancer-target-dn` role, and a `cached-reuse` runtime predicate. Each run
records planned, identity-matched, and applied faults separately. Only a
complete run with every fault applied **in the planned order**, on the same
Balancer manager/key ID, and with the KeyManager target guard
observed after the final fault contributes coverage feedback. A Balancer
JUnit failure remains an oracle candidate even if the target disappears
after the final fault. The campaign expands a valid sequence by one later
observed I/O point, prioritizing deeper repeated failures and new JaCoCo
method/branch coverage. It stops at queue or trial/time/fault budget
exhaustion and resumes from its checkpoint.

Balancer dispatch threads can race: one run logged ordinal 5 before
ordinal 4. Such a trial is retained with its trace but is not admitted as
the ordered `[4,5]` input; the runtime order is recorded explicitly.

The first planned ordinal is a negative control: its guard fetched a new
key, so its `cached-reuse` predicate did not match and no fault was applied.
The single fault at ordinal 2 matched a cached key and reached the same
guard again; the JUnit still passed. One earlier ordinal-3 JVM remained
alive after JUnit success. Its return code 124 is a harness timeout and
cannot contribute coverage. The raw timeout is retained in
`campaign/harness-timeout/p3/`; the case-local JUnit wrapper now exits
after JUnit completion to flush JaCoCo. The exact-plan queue stopped after
31 attempted trials when the separate DN-wire policy reproduced the known
issue. Thirty JUnit runs completed; 18 trials fully applied their planned
ordered faults, and 14 retained the target after the last fault. Three
candidates remain in the resumable checkpoint.

## Remote DataNode response calibration

The exact-plan and runtime-prefix client hooks throw IKE immediately before
the outbound `SaslDataTransferClient.socketSend` call. They exercise the
Balancer's catch/retry decision but bypass the SASL wire response. The
separate `campaign/dn-wire/` overlay instead selects a DEK only after
the Balancer `KeyManager` guard reports `refresh=false`. At the receiving
DataNode, `SaslDataTransferServer.getEncryptionKeyFromUserName` throws IKE
for that identified `(keyId, nonce)`. A probe in `doSaslHandshake` records its
`INVALID_KEY` response; the unmodified client decodes that response in
`DataTransferSaslUtil.readSaslMessage` and throws IKE to the Balancer.
The case records the Balancer manager/key ID, a short SHA-256 digest of the
nonce, target transfer address, receiving DataNode endpoint, and block-pool
ID. This is a synthetic DN rejection, not natural NameNode key rotation. A
one-rejection run verified the actual wire path but the original JUnit
still passed. An earlier keyId-only 20-rejection control timed out at the
original JUnit's 60-second limit. Its fixed run eventually passed after
all 20 rejections were consumed, because a refreshed DEK could retain the
same NN keyId; that is not a causal fix differential. The nonce-scoped
policy rejects the specific cached DEK, so a cache clear can create a
different nonce even when the NN keyId has not rotated.

## Known HDFS-17899 detection on the selected site

For the final differential, a case-local version of the original encrypted
Balancer JUnit calls the existing `TestBalancer.integrationTest(conf)` helper.
That helper invokes the original `oneNodeTest` MiniDFSCluster workload. The
test sets one Balancer mover thread and one concurrent DataNode move to keep
the rejection before the next use of the same `KeyManager`; its JUnit bound is
180 seconds. This is the encrypted one-node phase that the original
`testBalancer0Internal` runs first. The healthy run passed and moved all five
required blocks.

The selected fault is **one persistent state change** at the target DataNode:
the runtime-selected cached `(keyId, nonce)` DEK is rejected on every
subsequent SASL handshake. The cap of 1000 repeated responses protects the
harness; it is not a plan of 1000 separate faults. The instrumented DN sends
the actual `INVALID_KEY` SASL response. Only a short SHA-256 nonce digest is
logged, never the raw nonce or key material.

| Run | Remote INVALID_KEY | Old DEK guard checks after state fault | Cache clears | Successful moves | JUnit / Balancer |
| --- | ---: | ---: | ---: | ---: | --- |
| Healthy | 0 | 0 | 0 | 5 | pass / success |
| Hadoop 3.4.3 original | 23 | 44, all `refresh=false` | 0 | 1 | fail / `NO_MOVE_PROGRESS (-3)` |
| Original replay | 24 | 46, all `refresh=false` | 0 | 1 | fail / `NO_MOVE_PROGRESS (-3)` |
| Minimal HDFS-17899 fix | 1 | 0 | 1 | 5 | pass / success |

For the first original run, the selected Balancer manager was `1042578253`,
key ID `224550999`, nonce digest `aecdb5254d60`, and target DataNode
`127.0.0.1:44131`; the receiving DataNode endpoint matched. These values
are per-run identities, so the independent replay and fixed run use different
numeric IDs. In the fixed run, one remote rejection led to a cache clear and
then the same manager took the guard's `refresh=true` branch. The next DEK
had a different nonce; its key ID happened to remain the same. The fixed
Balancer moved all five blocks. Its normal success path does not print the
client's IKE stack; the observed DN `INVALID_KEY` response followed by the
case-local fix's IKE catch/cache clear establishes that the response reached
the client. The audit records this inference separately from a printed stack.

The source-side failure is precise: the original `Dispatcher.PendingMove`
records each SASL `IOException` as a failed move without clearing the DEK;
`Balancer` returns `NO_MOVE_PROGRESS` after five no-progress iterations
(`Balancer.java:766`, `ExitStatus.java:29`), and the original JUnit helper
asserts exit 0 (`TestBalancer.java:825`). This is an operation failure
beyond the intentionally injected exception. The minimal fix updates block
keys, clears the DEK, and retries once on a new socket. This run models a
stale DEK at the DataNode; it does **not** claim that a natural NameNode key
rotation occurred. It reproduces the *known* HDFS-17899 behavior at the
HDFS-55 check, and is not a new bug.

The runtime-prefix client-boundary campaign separately reached a 60-second
JUnit timeout at 12 cached-reuse injections. Its fixed replay passed but only
three faults matched before cache refresh. That timeout remains a candidate,
not the detection oracle. The DN-wire differential above uses an actual
remote SASL response and an operation-specific Balancer exit code.

The upstream HDFS-17899 PR's new
[`TestDispatcherEncryptionKey#testClearEncryptionKeyOnRetry`](https://github.com/apache/hadoop/blob/9b87ecc/hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/balancer/TestDispatcherEncryptionKey.java)
uses reflection to check that retry 1 updates block keys and clears the
cached DEK, while retry 2 refuses to repeat those actions. It is a narrow
fix-contract test; this case keeps the original 3.4.3 embedded-cluster
Balancer workload to check the operation outcome as well.

`campaign/campaign-evidence.tar.gz` stores the exact-plan and runtime-prefix
checkpoints, every completed trial's JUnit log, manifest, raw JaCoCo data,
derived coverage, the DN-wire original/fixed/replay runs, and the source
adaptation. `campaign/campaign-evidence-index.json` gives a SHA-256 for each
file. `campaign/dn-wire/qualification.json` contains the strict detection
checks. Trial scratch cluster directories were removed only after their
manifests and audit logs were preserved. The earlier
`known-bug-evidence.tar.gz` remains the first synthetic client-boundary
control.
