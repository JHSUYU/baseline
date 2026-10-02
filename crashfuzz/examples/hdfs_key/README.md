# HDFS encryption-key coordination check

This campaign evaluates the check immediately after
`BlockTokenSecretManager.retrieveDataEncryptionKey` reads `allKeys.get(keyId)`.
It uses the official Hadoop 3.4.3 binary without applying HDFS-17967/PR #8698.
The compiled method's first conditional branch tests whether the key exists;
the source-line throw is `InvalidEncryptionKeyException`. The workload creates
a file with three replicas over encrypted data transfer, then reads the file
back and compares SHA-256 hashes. It uses a NameNode and three independent
DataNodes, so a single DataNode can be crashed without destroying the cluster.

The Java agent correlates each data-transfer SASL connection by its client TCP
endpoint, adding request and response `MESSAGE` edges. The request edge runs
from the client or an upstream DataNode into the receiving DataNode's SASL
handler, which calls the target check. It also correlates Hadoop IPC requests
and responses by client ID and call ID, and traces task handoffs inside the IPC
client and server. A map update from `addKeys` to the target read is marked
`STATE_CANDIDATE`: the trace does not establish which map entry was read.
Missing or ambiguous edges are left as graph gaps. Fault points at the SASL
receive boundary and target method entry let the CrashFuzz-style search mutate
fault schedules using the target's backward closure.

From `baseline/crashfuzz`, after building the agent:

```sh
PYTHONPATH=src python3 -m adhoc_crashfuzz.cli run \
  --config examples/hdfs_key/campaign.json
```

Set `ADHOCFUZZ_HADOOP_DIST` if the Hadoop 3.4.3 distribution is not under
`~/.baseline-deps/hadoop-3.4.3`. `ADHOCFUZZ_KEY_WAIT_S` optionally inserts a
delay between write and read to cover key rotation. A `TARGET fatal=false`
event proves the exact compiled key-existence branch was evaluated; only an
actual throw at the configured line is counted as fatal. An injected crash
without that throw is a negative observation for that tested sequence, not a
proof that the check is unreachable under every possible fault schedule.
Run `python3 examples/hdfs_key/summarize.py examples/hdfs_key/out_fuzz` to
produce a per-run report with matched injections, branch outcomes, and closure
message edges.
