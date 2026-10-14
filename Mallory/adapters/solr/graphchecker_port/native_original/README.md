# Solr protocol source for the original GraphChecker engine

This patch starts from Apache Solr commit
`e27f44e3d78dfcec230c97e0a1240e3751daeff9`. It keeps the original
cluster JUnit unchanged. The patch is separate from the Mallory `TrialGraph`
Solr patch and calls the source-built original GraphChecker runtime classes.

Apply it to a clean checkout with:

```bash
python3 install.py --source /absolute/path/to/clean/solr
python3 install.py --source /absolute/path/to/clean/solr --verify-only
```

Compile the protocol overlay and JUnit runner with the Solr build's ordered
dependency classpath and the pinned original engine:

```bash
python3 install.py --source /absolute/path/to/patched/solr --verify-only \
  --write-attestation /absolute/path/to/source-attestation.json
python3 build_native_overlay.py --source /absolute/path/to/patched/solr \
  --source-attestation /absolute/path/to/source-attestation.json \
  --classpath-file /absolute/path/to/solr-classpath.txt \
  --engine-jar /absolute/path/to/mallory-original-graphchecker.jar \
  --output /absolute/path/to/isolated-protocol-classes
```

The attestation lets another host compile the same shared source tree when
its linked Git metadata is unavailable. The builder rechecks all patched
source and original JUnit bytes, rejects a changed engine, checks that every
dependency path exists, and records the ordered dependency classpath hash.
The classpath hash alone does not attest dependency file contents.
Without an attestation it verifies the pinned Git revision locally.

`communication-mappings.jsonl` declares one system-wide `byte[]` port from
the shared successful-write payload hook in `SolrZkClient.setData` and
`create` to `getData`. Solr's `ZkStateWriter` uses those writes for collection
state. One port avoids assigning the same read capture to two different
ports. Pass its absolute path as
`-Dcausynth.communication.mappings=...` to both the original static seed and
the `REGION_STATE` weave. A static flow remains a MAY edge; the trace must
still pair the same ZooKeeper path and data version. HTTP request context is
carried by the source patch and requires a matching receive. The mapping has
not yet passed a full Solr static/recording gate.

`source_receipt.json` pins the patch, all changed source files, and the
unchanged `DeleteLastCustomShardedReplicaTest.java` workload. The source
build must receive the original engine jar as `mallory.graphchecker.jar`.
The patch covers SolrJ HTTP request headers and server receipt, versioned
ZooKeeper reads and writes, Overseer queue selection, watcher callbacks,
server node identity, and exact one-ticket-per-submit ExecutorUtil work
handoff. With `causynth.cluster.automatic=true`, the selected queue item
carries its `mzxid` from the same `getData` call; a path-only queue ID is
never treated as a versioned read.

The original GraphChecker `MessageDoors.outbound` API records a send when
the header is prepared. A receive is still needed for an exact WIRE join;
an unreceived export is not evidence of a delivered message. This differs
from the two-phase Mallory runtime API. Native graph validation must inspect
the resulting paired endpoint and the target's backward closure.

## Shard-request worker handoff

For subsequent Solr campaigns, apply the separate
`solr-e27f44e-shard-request-handoff.patch` after the base protocol overlay:

```bash
python3 apply_shard_handoff.py --source /absolute/path/to/patched/solr
python3 apply_shard_handoff.py --source /absolute/path/to/patched/solr --verify-only
```

`HttpShardHandler.submit` creates a `ShardRequestor` and submits it to a
completion service. The overlay captures the current GraphChecker scope in
the requestor constructor and restores it around `call`, where the HTTP/2
request is issued. It applies to all shard requests, including collection
admin operations. The static planner recognizes selected `Http2SolrClient`
request calls as typed `IOException` doors and supplies the system-wide
Solr HTTP port when no explicit map is provided. These are MAY candidates;
the native trial must still observe the door, pair the HTTP request with a
server receipt, and retain the chosen target after the fault. The overlay
does not alter an original JUnit or nominate a case-specific fault site.

The 12 changed files passed source attestation. The 10 changed Java files
passed direct Java 8 compilation against the pinned source-built original
engine on node1, producing 47 classes. The unchanged
`DeleteLastCustomShardedReplicaTest#test` passed on node1 with the native
protocol overlay and runner, yielding a closed pre-weave trace with two
versioned Overseer queue receives. This
is a source and runner gate. A native `REGION_STATE` recording, target closure,
and fault trial still require the generated static scope and recording-derived
task plan.
