# HDFS-55: Balancer cached encryption-key coordination check

This supplements the original 102-site selection with the known HDFS-17899
check in Hadoop 3.4.3. The target is
`KeyManager.newDataEncryptionKey()` at `KeyManager.java:123`: the Balancer
reuses a locally unexpired cached key even when the destination DataNode no
longer accepts its key ID. The check spans NameNode-issued block keys,
Balancer cache state, and the remote DataNode SASL result. The original
embedded-cluster workload is the unmodified
`TestBalancerWithEncryptedTransfer#testEncryptedBalancer0` JUnit.

`build_overlay.py` instruments the exact KeyManager guard without changing
its boolean result and the outbound Balancer SASL call. Every event logs
the Balancer manager identity, cached key ID, target DataNode, guard result,
and whether it happened after a matched fault. The I/O exception hook is
stateful: it throws `InvalidEncryptionKeyException` on observed outbound
SASL attempts starting at a selected attempt and for at most a selected
number of attempts. This is a **synthetic stale-key fault**, not a natural
key-expiration reproduction. The fault sequence is selected using the
original JUnit's observed SASL attempts; no Docker cluster or graph is used.

The operation oracle is the original JUnit's Balancer block-move result and
exit status, supported by the repeated same-key guard outcome. A failed
injected I/O call by itself is insufficient. `jacoco.exec` and derived
covered method/branch files capture code coverage. Each trial writes its
own `manifest.json`, log, raw coverage, and a resumable campaign checkpoint.
The independent known-bug control lives at
`../../known-bug-controls/HDFS-17899/` and has already shown original 3.4.3
failure versus a minimal clear-and-retry fix. This site-level campaign
checks whether the new target guard is actually reached after a fault.

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
per run. This differential confirms the *known* HDFS-17899 Balancer symptom
at this added check; it is not a new bug. The checkpointed mutation budget
and case completion audit are separate followup work.

`known-bug-evidence.tar.gz` stores the three JUnit logs, manifests, raw
JaCoCo execution data, and derived coverage lists. `evidence-index.json`
gives a SHA-256 for every archived file. Trial scratch cluster directories
are excluded from the archive.
