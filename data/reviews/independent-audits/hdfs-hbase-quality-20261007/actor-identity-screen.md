# HDFS/HBase runtime actor identity screen

Read-only audit of terminal case evidence. This note does not change case results or
the shared checklist. A matched injection and a later execution of the same static
target site remain real observations; the question here is whether the raw evidence
joins both events to the same runtime DataNode, RegionServer, region, and cluster
startup episode when that relationship matters to the check.

## Exact list requiring a quality-status downgrade pending repair

`HDFS-22`, `HDFS-23`, `HDFS-24`, `HDFS-25`, `HDFS-26`, `HDFS-27`,
`HDFS-34`, `HDFS-35`, `HDFS-37` (nine cases, three original-JUnit campaigns).

| Shared campaign | Cases | Reported trials with target after fault | Runtime identity gap |
| --- | --- | ---: | --- |
| `TestDFSStartupVersions#testVersions` | HDFS-22/23/25/34/35 | 57/57/57/20/62 of 80 | The RPC key uses a digit-stripped thread name; target records do not carry a DN, storage directory, or startup episode. |
| `TestDFSUpgrade#testUpgrade` | HDFS-24/27 | 53/48 of 80 | Same RPC key; the two target probes record comparison values but no DN, storage directory, or startup episode. HDFS-27's file selector can distinguish `dfs/data1` and `dfs/data2`, while its target cannot. |
| `TestDFSRollback#testRollback` | HDFS-26/37 | 69/61 of 80 | Same RPC key and unkeyed target. A raw four-fault trial demonstrably collapses two concrete RPC endpoints into one normalized family. |

The problem is not a missing global fault count. In `HDFS-22/independent/src/Hdfs22Probe.java`
lines 105-125 and `HDFS-37/independent/src/HdfsStorageProbe.java` lines 165-190,
`Client.getRpcResponse` selects on `thread.replaceAll(":\\d+", ":port").replaceAll("\\d+", "N")`,
site, and ordinal. This merges all `Thread-<number>` responses and removes the
heartbeat endpoint port. File keys preserve a normalized `dfs/data1` or
`dfs/data2` path, but the target events log only thread, check site, and values.
The original tests repeatedly start DataNodes with different storage/version
settings in one JUnit execution. Later `TARGET_CHECK` on a different startup
thread therefore cannot by itself establish a target check on the faulted DN
instance or episode.

Concrete raw receipts:

* HDFS-26 run `173f396d08b8c8de/attempt-1` has four matched/applied RPC
  faults and is marked `exact_order_applied=true`, `target_after_fault=true`,
  JUnit pass. Its `runtime_trace.jsonl` seq 66/81 reports concrete heartbeat
  endpoint `localhost:36907`, while seq 141/155 reports `localhost:32825`;
  all four have the same normalized `sourceKey` and ordinal series. The later
  HDFS-26 checks at seq 165/166/173/174 are on `Thread-2771` and contain no
  DN/storage/cycle key. See
  `HDFS-26/independent/evidence/runs/173f396d08b8c8de/attempt-1/runtime_trace.jsonl`
  and its `campaign-state.json` row.
* HDFS-22 run `125683115f5be6b2/attempt-1` has a normalized `Thread-N`
  fault at seq 105 on concrete `Thread-734`. Its four later HDFS-22 checks
  are on `Thread-940`, `Thread-1054`, `Thread-1165`, and `Thread-2203`
  (seq 171/183/196/246). The campaign admits this as post-fault target,
  but no target record identifies the faulted DN/cycle. The healthy trace's
  `Thread-N` family itself merges `Thread-66`, `Thread-90`, `Thread-104`,
  and many later threads under one ordinal stream. See
  `HDFS-22/independent/evidence/{healthy,runs/125683115f5be6b2/attempt-1}/runtime_trace.jsonl`.
* HDFS-37 run `2343c570ffdf5ed3/attempt-1` injects on `main` at seq 114,
  then reports HDFS-37 targets on `Thread-1475` and `Thread-2173` at seq
  119/120/127/128. Its `TARGET_CHECK` has no directory or DN field. See
  `HDFS-37/independent/evidence/runs/2343c570ffdf5ed3/attempt-1/runtime_trace.jsonl`.

Some archived file-fault trials have a same-thread later check, which can
support an individual local relation after source review. They cannot repair
the already counted RPC-heavy budgets: among target-retaining trials, 46/57,
47/53, 61/69, and 51/61 in the HDFS-22, HDFS-24, HDFS-26, and HDFS-37
campaigns respectively requested at least one RPC fault. Raw traces lack
the DN/cycle field needed to certify those trials offline. The nine cases
should be marked `needs_actor_identity_recheck` or equivalent until the
fault and target probes share a stable DN/storage/episode ID and a resumed
campaign fills a valid budget. Keep the original raw counts and measured
times as historical observations rather than deleting them.

## Cases retained in this screen

HDFS-28/29/30 use a materially different recovery probe. Their healthy raw
trace records `RECOVERY_BEGIN` with origin `dn1`, block 1073741825 and
attempt 1; each selected `TARGET_CHECK` carries the same `sourceKey`, block,
recovery ID, attempt, and `occurrenceAddress`. Server-side replica-file I/O
records both `originSourceKey=dn1` and `sourceKey=dn0` or `dn1`, with the
server DN in its occurrence address. The remote RPC fault point lacks a
separate destination DN field, a residual limitation for comparing remote
replicas, but it preserves the origin recovery identity required to join to
these targets. See
`hdfs_recovery_shared/phase-v4/healthy-file-phase/runtime_trace.jsonl`.

HBASE-29/30 selectors contain table and replica ID but omit encoded region
and receiving RS. The original test has one selected replica region per run;
all 80 archived trial logs for each case were searched, and none contained
more than one `ENTRY_AFTER_GUARD` encoded region. Thus there is no observed
within-run region collision. This is a selector hardening opportunity, not
evidence for revoking these two results. HBASE-10/11/12 RPC hashes omit
destination, but their original JUnit drives one named region and a single
master; no raw actor collision was established in this screen. HBASE-01/02
client-side meta I/O logs likewise do not prove a physical RS match, but
their selected checks are client connection checks and no contradictory
actor trace was found. These HBase results remain flagged for future
instrumentation hardening without a status recommendation here.
