# HDFS-01 actor-aware recheck

The selected Hadoop 3.4.3 check is `DFSInputStream.fetchBlockAt` at source
line 517. An empty `LocatedBlocks` response causes its line-518
`EOFException`. The unchanged workload is
`TestPread#testPreadDFS`, which starts a three-DataNode `MiniDFSCluster` and
performs positional reads. The selected exception is the oracle; an injected
I/O exception or unrelated JUnit failure is not itself a bug report.

The previous 128-attempt campaign remains in `../evidence/`. Its data-transfer
read selector keyed only by client thread and global ordinal, so its 98
post-fault target visits cannot be counted as actor-proven effective trials.
This recheck uses a separate bytecode overlay, healthy seeds, queue and
checkpoint. It does not read a causal graph or start Docker.

## Runtime identity

`PatchHdfs01Actor.java` hooks the exact target condition and throw, the
client's `getLocatedBlocks` return, and
`BlockReaderRemote.read`. `Hdfs01ActorProbe.java` records each returned
block's file, start offset, block ID, DataNode UUID and response replica
index in raw `BLOCK_LOCATION` events. The first block is learned from the
file-open response, before the selected `fetchBlockAt` check. Each read
records its actual live DataNode UUID and block ID, then matches it to the
same run's preceding response. If this join fails, the point cannot inject.

A plan names the file/block start offset and response replica index; its
physical DataNode UUID is resolved afresh each run. This is a logical
position in the response, not a claim that replica index names the same
physical server across clusters. The independent auditor joins raw
`BLOCK_LOCATION` and read events again. Client-to-NameNode I/O is scoped to
the original JUnit's main/DataStreamer threads; this workload has one
NameNode. The target receipt binds the post-fault check to `/preadtest.dat`.

The V2 calibration exposed the missing first-block binding: two original
JUnit runs passed with 18 target checks and six reads each, but only four
reads per run were bound. Those runs and three strict pilot trials are
preserved under `healthy-a/b`, `healthy-v2-a/b` and `campaign/` solely as
instrumentation-development evidence. They do **not** count toward V3's
effective budget.

The V3 overlay adds the file-open response and raw location receipts. Two
fresh original JUnit runs passed in 22.021 and 21.420 seconds. Each had 18
selected checks and all six data reads bound; all 12 reads independently
join to raw block-location events. Six actor/resource/ordinal selectors were
common across both seeds. The receipts are `healthy-v3-calibration.json` and
`build/receipt.json` on node1. The latter records source and patched-class
hashes. `smoke_offline.py` checks wrong-UUID rejection and ordered faults
without starting a cluster; the four patched classes also pass ASM's
`CheckClassAdapter`.

## V3 campaign

`campaign.py` initializes from the **union** of both healthy JaCoCo coverage
sets and stable observed I/O. It mutates only an effective run by adding one
later observed I/O fault. A trial is effective only when all planned faults
apply in order, every faulted read's raw DataNode/block join verifies, and
the selected check on the same file executes after the final fault.
Unmatched, target-lost and timeout attempts remain recorded but do not
contribute coverage or descendants. `audit_campaign.py` independently
recounts this from each original JUnit's manifest, trace, plan and JaCoCo
files. The queue and current plan are atomically checkpointed at
`campaign-v3/checkpoint.json`; a completed trial is never replayed on resume.

The base budget is **80 effective trials / up to 8 ordered faults**, with an
attempt cap of 320. If the final eight effective runs add production method
or branch coverage or a stable relevant I/O family, the same checkpoint
extends to **128 effective / up to 10 faults** and an attempt cap of 512.
An early queue or attempt-cap stop is reported as unfinished, not as a
completed check. A target `EOFException` is a candidate requiring exact
replay and source review before any new-bug claim.

Node1 runs the case in tmux using the exact original JUnit and isolated
scratch directories. `calibrate.py --prefix healthy-v3` produced the two
healthy seeds. The first three V3 fault trials are a bounded pilot; the full
runner resumes the same checkpoint after its raw audit.

## Final audited result

The V3 campaign stopped at its base budget: **114 attempts, 105 exact ordered
injections and 80 effective same-file post-fault target visits**. The original
JUnit returned 0 in 89 fault trials and 1 in 25; a JUnit failure alone is not
the selected exception oracle. No fault trial produced the selected target
`EOFException`, so this case has no new-bug mark. The two healthy JUnits and
114 fault JUnits consumed 2,257.742 seconds of summed JUnit time. The longest
executed plan contained five faults.

Compared with the union of both healthy runs, effective trials added 176
production probes, 22 methods, 100 branch-count identifiers, 190 lines and
six actor-bound I/O families. The final eight effective trials (attempts 96,
99, 104, 108, 110, 111, 112 and 114) added none of those method/branch/I/O
feedback categories, so the conditional 128/10 extension did not activate.
`audit-final-v3.json` independently recomputes all 114 plans against raw
manifests, trace events and JaCoCo files, including 904 raw read-to-location
joins. It records the final checkpoint SHA and duration breakdown. The raw
trial directories remain on node1 under `campaign-v3/trials/`; the checkpoint
retains 1,476 untested plans for any future, separately authorized budget.
`raw-evidence-sha256-v3.txt` hashes the 1,140 top-level raw trial files on
node1 (manifest, plan, trace, coverage and logs); its own SHA-256 is
`ff98a8330b9cd304068d54036a3dae1082091d45020b03a95242f1558a7f24ee`.
