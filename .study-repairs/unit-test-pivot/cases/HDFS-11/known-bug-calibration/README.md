# HDFS-17967 outbound-path calibration (known issue)

This is a **known-bug path control**, separate from the 102-site checklist and
from the count of newly discovered bugs. Apache [HDFS-17967 / PR #8698](https://github.com/apache/hadoop/pull/8698)
identifies missing local `InvalidEncryptionKeyException` recovery in
`DataXceiver.writeBlock` (mirror), `DataXceiver.replaceBlock` (proxy), and
`StripedBlockWriter.init`. The released Hadoop 3.4.3 bytecode is used here;
the comparison uses the source tests and the PR description, not a claim that
the release already contains the fix.

## Original workloads and observation

* `TestEncryptedTransfer#testEncryptedWriteWithTwoDns[0]` supplies a two-DN
  encrypted MiniDFSCluster and reaches the mirror `socketSend`.
* `TestBalancerWithEncryptedTransfer#testEncryptedBalancer0` supplies an
  encrypted embedded cluster and reaches proxy `socketSend` during balancing.

`prepare_overlay.py` copies the HDFS-11 target-check recorder, then adds one
ASM hook to the production `SaslDataTransferClient.socketSend` entry. The hook
records which `DataXceiver` operation called the outbound I/O and can throw
one synthetic `InvalidEncryptionKeyException`. It does not replace the JUnit
workload, use Docker, or run GraphChecker. `run_control.py` executes the
original parameterized JUnit and records the full log, I/O trace, exact HDFS-11
`allKeys.get(keyId)` check trace, JaCoCo raw coverage, and elapsed time.

| Path | Healthy run | Fault run | Fault match | Local result | JUnit |
| --- | ---: | ---: | --- | --- | --- |
| Mirror `writeBlock` | 25.133 s | 21.240 s | first observed mirror SASL send | `Exception transferring block ... to mirror`; pipeline recovery | both pass |
| Proxy `replaceBlock` | 43.855 s | 35.856 s | first observed proxy SASL send | `opReplaceBlock` reported move failed; balancer later continued | both pass |

In both fault runs, the requested exception was applied exactly once. Source
review shows that 3.4.3 propagates it directly from the outbound SASL call;
PR #8698 adds socket close, cached-key clear, and one local retry at those
same call sites. These synthetic outbound exceptions occur **before** the
receiver checks `allKeys.get(keyId)`: the check trace shows no missing-key
branch or target throw in either fault run. The passing outer JUnits therefore
must not be labeled as two new bugs or as reproduction of the complete stale
key scenario. They establish the previously unobserved I/O paths and the
missing local recovery behavior. The separate [HDFS-17897 control](../../../known-bug-controls/HDFS-17897/README.md)
reproduces a real expired-key target exception and a failing operation on
Hadoop 3.4.3, with a passing minimal fix comparison.

## Method change from this control

For an encryption-key candidate, a healthy seed is admissible only if its
embedded cluster reaches both the selected check and a relevant NN→DN or
DN→DN encrypted transfer. A one-DN ordinary read is insufficient for mirror
and proxy transfer. The fault corpus should retain I/O identity including
operation, sender/receiver role, peer, block or file, and occurrence; code
coverage remains a scheduler signal. A synthetic exception at the outbound
call is evidence of that path's error handling. For the actual
`allKeys.get(keyId)` oracle, cause a real stale key at the receiving DN and
record the selected guard outcome; then check whether the operation retries
or fails. Keep target-check observations, operation outcomes, and new-bug
confirmation separate.

Run `python3 summarize.py` to recheck the four traces and regenerate
`result.json` and the SHA-verified raw evidence archive at
`evidence/hdfs17967-outbound-controls.tar.gz`.
