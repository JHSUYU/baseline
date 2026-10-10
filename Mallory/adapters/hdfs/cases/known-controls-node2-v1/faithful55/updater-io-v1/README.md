# HDFS-55 faithful Balancer updater I/O differential v1

Status: **source patched and no-JVM checked; runtime unverified**. This is a
separate adaptation of Hadoop 3.4.3's encrypted one-node
`TestBalancerWithEncryptedTransfer#testEncryptedBalancer0`. It does not replace
the original-JUnit 80/3600/max3 Mallory campaign, does not count in the
original 102, and makes no HDFS-17899 detection claim.

The case-local `TestBalancer` overlay shortens the active NameNode master key
interval and token lifetime to 2000 ms, then waits for a **post-start** key
`k` to become current and reach the new destination DataNode. The Balancer
`KeyManager` constructor fetches that key normally. The only injected fault
is a typed `IOException` immediately before the *background updater's*
`namenode.getBlockKeys()` call. The gate matches that Balancer manager,
NameNode proxy and endpoint, block pool, and updater actor; the fixed
foreground `updateBlockKeys()` RPC is unaffected. This is one persistent
outage window with repeated call exceptions, not three independent Mallory
faults. It needs separate fault-model admission.

The first Balancer move waits until the NameNode has retired and removed
`k`, the destination DataNode has naturally pruned `k` during a successful
`addKeys`, and both have the newer current key. The read-only probe records
NN rotations, expiry times, DN UUID/manager/map keys, Balancer manager and
cached `(keyId, nonce digest)`, exact DN `allKeys.get(keyId)` result, and
native `INVALID_KEY` wire response. No code writes the DN map or overrides
the lookup result. The direct map override in `../../adapted55/` remains a
**synthetic diagnostic only**.

The fixed comparison uses the historical minimal clear-and-retry patch. A
positive candidate requires a passed healthy JUnit, repeated original
`refresh=false` reuse of the same `(k, nonce)`, native DN
`InvalidEncryptionKeyException`, `NO_MOVE_PROGRESS` and JUnit failure with
no cache clear, then a fixed foreground NN refetch of `k'`, cache clear,
successful retry, and passing JUnit under the same outage policy. The
case-local `audit.py` rejects missing identities, earlier block-token/SASL
failure, or a missing natural DN null lookup. Even a complete machine
candidate keeps `detection_claim=false` for review of the archived trace.

Run `python3 prepare.py --static`, `python3 -m unittest test_static.py`, and
`python3 run.py --static` for no-JVM checks. Node2 dispatch may later run
`MALLORY_DISPATCH_ADMITTED=1 python3 run.py --run --output
/tmp/mallory-hdfs55-faithful-updater-io-v1-node2` under the shared
`hdfs-identity-v8-node2.lock`, with a fresh output path and 6 GB reserve.
The runner first requires the modified healthy JUnit to pass, then runs
original and fixed fault phases, writes SHA-bound manifests, `audit.json`,
an archive, and a terminal receipt. No live JVM has run for this package.

Risks requiring runtime admission: the 180-second JUnit may not allow both
natural key retirement and Balancer no-progress completion; the 2000 ms
token lifetime may cause an earlier failure; Balancer may construct its
manager after `k` rotates; and a move may not reach the selected DN lookup.
Each is an explicit negative or incomplete result, not evidence that the
selected coordination bug was detected or impossible.
