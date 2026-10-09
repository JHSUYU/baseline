# HDFS-34 trial `01019f4aa1c6312fa362`: expected control rejection

Source: Hadoop `rel/release-3.4.3`,
`TestDFSStartupVersions#testVersions` and `DataStorage.doTransition`.
This is an offline review of saved node1 evidence. No replay was started.

## Exact fault and target

- The one-step plan injected `IOException` at
  `Client.getRpcResponse`, `episode=6/dn=1/dirs=dfs/data1/peer=NN0`, hit 1.
  The raw runtime trace records `FAULT_APPLIED` at seq 114 with the exact
  actor and raw NN0 endpoint `localhost/127.0.0.1:38457`. RPC hit 2 at seq
  164 shows the actor retried and proceeded.
- `DataStorage.doTransition#L740-IF_ICMPEQ` then compared the same actor's
  `dfs/data1` stored namespace ID `-2147483648` to NameNode namespace ID
  `2123651051` at seq 166. It threw `java.io.IOException` at seq 167.
- The original JUnit finished with one test, zero failures, exit 0 in
  42.462 s. Its log names this iteration `testCase=5` and records
  `isVersionCompatible=false` because namespace IDs are unequal.

## Healthy controls and source meaning

| Run | Episode 6 check | Episode 6 throw | JUnit |
| --- | --- | --- | --- |
| Healthy a | seq 116: stored `-2147483648` vs NN `2106662798`, unequal | seq 117: same `IOException` class on `dfs/data1` | exit 0, 37.944 s |
| Healthy b | seq 113: stored `-2147483648` vs NN `1114556356`, unequal | seq 114: same `IOException` class on `dfs/data1` | exit 0, 41.562 s |
| Faulted | seq 166: stored `-2147483648` vs NN `2123651051`, unequal | seq 167: same `IOException` class on `dfs/data1` | exit 0, 42.462 s |

`initializeVersions` sets `namespaceIdOld = Integer.MIN_VALUE` and places
that value in array entry 5. `testVersions` writes each entry's VERSION file,
starts one DataNode, and permits startup to throw; its compatibility check
explicitly says unequal namespace IDs mean startup must fail. The faulted
trace reached the same check after an RPC retry and took the same intended
rejection path. This target throw is **pre-existing in both healthy seeds**;
there is no evidence here of a new coordination bug.

The saved controller result correctly retains one postfault target throw and
one effective check. Its historic `target_exceptions_matching_healthy_signature`
value was zero because the original healthy receipt lacked that annotation.
The read-only `audit_checkpoint.py` now derives stable signatures from both
healthy traces (case, actor, storage volume, check site/outcome, stable stored
operand, exception class). It reports one HDFS-34 target throw matching both
healthy controls and zero novel signatures. It does not change the raw trial,
fault order, effective count, or campaign checkpoint.

Node1 evidence root:
`/users/ZhenyuLi/baseline/crashfuzz/hdfs-storage-actor-v2/evidence/startup-constructor`.
The faulted attempt is `runs/01019f4aa1c6312fa362/attempt-1` with trace
SHA-256 `ed4c8ff3e89ceffaae545ec253b2efd313ad8260301276c77f0beec88f7b8a6b`
and manifest SHA-256
`7b18757098e29a4a5bd891afa79bdfbd38518f4ad2fa716561f49dbda8dfd74e`.
Healthy trace SHA-256 values are
`e2bb1a3391f96f9b1c3a44b4b9db6e6c6a635bbde84bc065e9b6ca326ef6c317`
and `147ecdc215f77052f015f5bb807525f015d96250bface4ec526c70296b92c0c1`.
