# HDFS-17899 calibration: stale key during Balancer block moves

**Known upstream bug control, not a new bug and not one of the 102 candidate
checks.** This controls the Balancer portion of HDFS-17899 on the released
Hadoop 3.4.3 code. The original embedded-cluster workload is unchanged
`TestBalancerWithEncryptedTransfer#testEncryptedBalancer0`, loaded from the
3.4.3 test JAR with the tagged source tree's original test resources. It
starts real NameNode/DataNode processes in a MiniDFSCluster and moves blocks
between DataNodes. No Docker cluster or GraphChecker runtime is involved.

## Source and fault identity

In 3.4.3, `Dispatcher.PendingMove#dispatch` obtains a cached
`DataEncryptionKey` through Balancer `KeyManager` and calls the six-argument
`SaslDataTransferClient.socketSend` on the target DN connection. Its generic
`IOException` handler records a failed move and does not clear the cached
key. The upstream [HDFS-17899](https://issues.apache.org/jira/browse/HDFS-17899)
fix ([PR #8383](https://github.com/apache/hadoop/pull/8383/files)) adds a
bounded clear-key-and-retry path to this and two other outbound call sites:
SPS `BlockDispatcher.moveBlock` and `DataNode.DataTransfer.run`.

Our case-local ASM hook targets **only** that Balancer SASL method call,
checked by the live `Dispatcher$PendingMove.dispatch` stack frame and the
target DN address. When injection is enabled it throws
`InvalidEncryptionKeyException` at the connection setup boundary until the
cached key is cleared. This is a **stateful synthetic exception**, modeling
the failed SASL connection after stale key propagation. It is not a natural
key-expiry reproduction; HDFS-17897's companion control uses actual NN key
rotation and expiry. The control logs Balancer key ID, target DN, each SASL
attempt, cache-clear event, and block-move results. The injection happens
before a block replacement request is sent.

The fixed comparison overlays only the 3.4.3 `Dispatcher.java` and
`KeyManager.java` classes with the minimal PR-style bounded retry and cache
clear. `fix-control.diff` records all source changes. Both original and fixed
runs use the same JUnit and fault hook. HDFS-17967 addresses distinct
DataXceiver/StripedBlockWriter outbound paths; this experiment does not claim
to test those paths.

## Reproduce

```sh
python3 build_overlay.py --mode original
python3 build_overlay.py --mode fixed
python3 run_control.py --output evidence/healthy-04
python3 run_control.py --overlay build/original-overlay --inject --output evidence/original-fault-01
python3 run_control.py --overlay build/fixed-overlay --inject --output evidence/fixed-fault-01
```

The release source test resources include `hdfs-site.xml` with a zero NN
minimum block size. Two setup attempts were excluded before finding that
resource: `healthy-01` lacked Mockito on the classpath and `healthy-02`
rejected the original test's 100-byte blocks. `healthy-03` used a case-local
equivalent block-size resource and passed; `healthy-04` uses the exact tagged
source test resource and is the reported healthy control. All logs remain in
the raw evidence archive; setup runs are not counted as fault trials.

## Results

| Run | Time | SASL faults | Cache clears | Successful moves | Original JUnit |
| --- | ---: | ---: | ---: | ---: | --- |
| Healthy | 31.182 s | 0 | 0 | 15 | Pass |
| Original 3.4.3, injected | 58.904 s | 20 | 0 | 0 | Fail: Balancer returned −3 instead of 0 |
| Fix control, injected | 37.035 s | 1 | 1 | 15 | Pass |

The 20 original-side faults reuse the same cached key ID and include source
`Failed to move` events; no block is moved. In the fixed run, the first
fault triggers a cache clear, the next SASL setup succeeds, and the original
JUnit's balancing oracle passes. The result relies on downstream block-move
success and the original JUnit result, not on observing the injected exception
alone. See `result.json` for per-run metadata and SHA-256 hashes. Full logs
and manifests are in `known-bug-evidence.tar.gz`.

## Baseline implication

The graph-free I/O selector should include the specific role and call stack:
Balancer-to-target-DN SASL, plus the `KeyManager` key-refresh operation that
can change the next attempt. A one-shot fault would let later Balancer moves
succeed and may miss the persistent stale-cache behavior. Feedback should
retain key ID, target DN, block ID, retry/clear branch, failed and successful
moves, and the final Balancer outcome. Code coverage can prioritize the retry
branch; the operation outcome is the failure oracle. The same I/O family
should be considered for SPS and DataNode replication as separate call-site
controls, with their own operation-specific oracles.
