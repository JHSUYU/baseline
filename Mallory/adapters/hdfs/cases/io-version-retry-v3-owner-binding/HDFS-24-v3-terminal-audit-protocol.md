# HDFS-24 v3 terminal retry audit

The immutable 80-trial campaign uses `TestFileTruncate#testUpgradeAndRestart`,
an existing `MiniDFSCluster` test. Run `audit_hdfs24_full_retry.py` only on a
terminal, SHA-archived copy, with `--out` outside the campaign directory. Its
output binds the full config, terminal result, offline audit, and **every file**
under the campaign root by SHA-256. It verifies each trial's gzip and raw trace
hashes, JUnit receipt, site catalog, and exact fault point before classifying
individual faults.

A strict witness needs the exact named DataNode
`BPServiceActor.retrieveNamespaceInfo@260:door:1` `IOException` application,
then another door on the same DN, epoch, numeric thread and occurrence, a
request SEND with one unique Hadoop IPC correlation token, a named NameNode
request RECV and response SEND on one NN thread/occurrence, a DN response RECV
on the original DN thread, and the exact `BlockPoolSliceStorage.doTransition`
branch check inside a region parented by that response token. All events must
have increasing trace sequence numbers. Other faults and missing or ambiguous
links receive explicit negative classifications; target retention alone does
not establish a witness. Multi-fault witnesses list any intervening applied
fault IDs to avoid attributing a later check to one exception alone.

The code path supports the retry interpretation: `BPServiceActor.java`
lines 255–273 calls `bpNamenode.versionRequest()` inside an `IOException`
catch and retries after sleeping. Source SHA-256:
`fbcb03b86822e71e451242142752706b61c3f3f096d0219f5d90344bc59bb833`.
The selected `BlockPoolSliceStorage.java` check at lines 414–424 compares
layout version and cTime; its `IOException` reports a DataNode state newer
than the namespace and deliberately shuts down rather than accepting an
unsafe version transition. Source SHA-256:
`3234d407e842dbc76ec4fd5c0671b39108988dfa36b6c6dea9d10f3ad949be8e`.
An exact target throw therefore requires separate state-value, replay, and
API-contract review before any bug claim. The auditor reports throw counts
without labeling a bug.

Example terminal command:

```sh
python3 Mallory/adapters/hdfs/cases/io-version-retry-v3-owner-binding/audit_hdfs24_full_retry.py \
  data/mallory/cases/HDFS-24 \
  --out data/mallory/quality_reviews/hdfs24_v3_retry/HDFS-24.json
```

The two-fault pilot is only a verifier check: it yields two strict witnesses
and zero exact target throws. A copied live full-trial sample `r0015` yields
one negative retry-path classification and one unrelated-site fault; `r0030`
yields one strict witness and one unrelated-site fault. These samples are not
a terminal campaign result. `test_audit_hdfs24_full_retry.py` has eight
positive, tamper and negative tests. Keep report high-quality status pending
until the terminal sidecar has been independently checked and registered by
the report owner.
