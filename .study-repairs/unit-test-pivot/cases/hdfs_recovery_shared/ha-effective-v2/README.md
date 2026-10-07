# HDFS-28/29/30 original HA JUnit effective-budget campaign

This directory is isolated from the running `phase-v4` recovery campaign. It
uses the unchanged released Hadoop 3.4.3
`TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization` method.
That method calls `newMiniCluster(conf, 3)` and the helper creates three
NameNodes and three DataNodes (`TestPipelinesFailover.java:87,328,418–422`).
It waits for the first block synchronization request, changes NN0 to standby
and NN1 to active, then retries lease recovery. The original project's
`hdfs-site.xml` is supplied on the test classpath; without it, the original
4 KiB test block is rejected before recovery begins. The JUnit's operations
and assertions remain in the released test JAR.

The copied `PatchRecovery.java` and `RecoveryProbe.java` instrument the three
`BlockRecoveryWorker` checks, observed remote recovery RPC sends, and
`FsDatasetImpl.checkReplicaFiles` reads. Each injected exception is matched
against marker, bytecode site, physical DataNode, recovery occurrence, hit
ordinal, and file phase. The runtime trace records `RECOVERY_BEGIN`, server
recovery handoff, matched/applied faults, checks, and selected throws. The
case-local probe refuses to attribute a remote file read if two recovery
owners share the same observable `(block pool, block ID, recovery ID)` key.
This is conservative because the original RPC does not carry a full local
recovery-root identifier. `CoverageRecovery.java` keeps stable JaCoCo probes,
methods, and covered branch counts only for classes in the released HDFS,
HDFS client, and common production JARs. No GraphChecker graph or runtime
JAR is loaded.

`run_original.py` creates a fresh embedded cluster for each run. Its first
two instrumented no-fault runs are `healthy-a` and `healthy-b`; both must
pass and reach all three checks on nonfatal branches. Only their observed
I/O before a later target check on the same recovery owner seeds the queue.
After each faulted run, the controller may add exactly one later observed
I/O exception to a sequence. It favors unresolved targets, untried exception
types/I/O families, coverage and I/O novelty, and sequences up to six faults,
while aging queued inputs. The saved sequence is ordered; the controller does not
schedule every nonfault I/O event.

Each check needs 80 **effective** trials with at most eight ordered faults.
The last eight effective trials are inspected at that check's 80th trial;
new production methods, covered branch counts, or I/O families extend that
check to 128 effective trials and permit sequences of at most ten faults.
The shared run has a 320-attempt cap, raised to 512 on extension. A trial is
effective for a particular check only when every selected fault matches and
applies in order with a verified physical recovery owner, then that exact
owner/root/block reaches the selected check after the final fault. A lost
target is an attempt but never an effective trial. A selected postfault
`IOException` throw is a candidate for independent replay and source review,
regardless of JUnit exit status. JUnit failure alone is not the oracle.

The controller writes `checkpoint.json` atomically after each completed
trial. Its `active` plan persists across interruption, and a complete
`runs/trial-NNNN/manifest.json` prevents that JUnit from being rerun after a
restart. Each trial keeps its fault plan, raw trace, JUnit log, JaCoCo file,
derived coverage, elapsed seconds, and SHA-256 trace receipt. The controller
also updates `summary.json` and the three-case `trial-ledger.csv` after every
trial; the table has the exact site, requested fault count, duration, strict
match, target visit, target exception, and code/I/O feedback for each check.
`audit_raw.py`
parses these files independently of `campaign.py` and recomputes ordered
fault matching, physical identity, postfault target visits, selected throws,
coverage/I/O novelty, timing, and final unions. It writes `raw-audit.json`.
An attempt cap with fewer than 80 effective trials is **inconclusive**.

The first fresh instrumented healthy run failed the original JUnit's
60-second timeout with no fault selected; its manifest, raw trace, JUnit log,
JaCoCo output, and derived coverage are preserved under
`failed-healthy/healthy-a-001`, with per-file hashes in `archive-receipt.json`.
This run is excluded from both calibration and the fault budget. The retried
`healthy-a` and `healthy-b` passed the original JUnit in 26.766 and 27.308
seconds. Their raw traces passed the independent `audit_raw.py` baseline
check (zero errors). A bounded first fault trial was then launched from the
new atomic checkpoint; subsequent work resumes that checkpoint.

The campaign can be inspected or resumed with:

```sh
python3 campaign.py --preview
python3 campaign.py --run --max-new-attempts 1
python3 campaign.py --run
python3 audit_raw.py
```

`provenance.json` records released JAR, original test class, original source,
test resource, and local adapter hashes. The old `phase-v4` probe's malformed
`TARGET_THROW` JSON field is fixed in this copy. The original HA single-file
pilot (`phase-v4/ha-smoke-file-b`) was evaluated offline with this controller:
one strict same-owner file failure left HDFS-28/29/30 reachable after the
fault and gained 29 stable probes, three methods, and 22 covered branch
count units per target. It is **not** counted in this new campaign.

The original two-file HA pilot on node1
(`phase-v4/ha-two-file-pilot-node1-02`) applied two ordered replica-file
`IOException`s in `dn1/block:1073741825/attempt:1`; the released JUnit
passed in 29.33 seconds. Offline recalculation with this controller found
one later HDFS-29 and HDFS-30 check, zero later HDFS-28 checks, and zero
selected throws. This pilot is also excluded from the new budget. Its raw
trace SHA-256 is
`94d02ee44c71bc97f927a120498e4c65f24b287a9bf5c717fcfc5ddc2115ffc8`.
The node1 phase-v4 probe source SHA-256 was
`d41c4e4558e6fc0e57920cef26663b0fa74084ad7f14dbc0784b57b404130f56`,
and the built overlay probe class was
`f263504ff3dc85a8aac70b2029ae68c29c9b0f75befe16b34ed6751990bd08e4`.
The node1 build marker was newer than that source. The new case-local probe
adds conservative ambiguity detection and has a separate hash in
`provenance.json`; these historical pilots do not validate that new build.

`archived-pilot-receipt.json`, regenerated by `audit_archived_pilots.py`,
records the raw trace, JUnit log, JaCoCo, manifest, and plan hashes of all
three later HA pilots. Pilot 01 missed both requested sites and the JUnit
passed. Pilot 02 matched both sites and left HDFS-29/30 reachable as above.
Pilot 03 requested two remote DataNode file exceptions but matched neither;
the original JUnit's 60-second annotation timed out (`exit=1`, 63.406s
including startup/shutdown). Because no fault was injected and no selected
postfault target was observed, pilot 03 is neither effective nor a bug
candidate. All three remain outside the new 80/128 effective-trial budget.

## Natural-boundary successor

`successor.py` is prepared for the running node1 campaign. Do not copy it to
node1 or launch it while `hdfs_ha_effective_full` is running. At the old
controller's natural complete boundary (12-hour wall cap or attempt cap),
first confirm that its tmux command has exited, the last trial has a full
manifest and trace, and `checkpoint.json` has `active: null`. The successor
also takes `campaign.lock` nonblocking; it refuses to touch the checkpoint
while the old controller holds that lock. It verifies the old `campaign.py`
SHA-256, the last completed trial's plan, manifest, and raw trace SHA-256.
It then runs `audit_raw.py` against every completed trial and refuses the
handoff if the independent audit finds any inconsistency.

The handoff retains the complete `completed`, `queue`, and `seen` lists. It
records a five-slot scheduler with four RPC slots and one file-I/O slot,
considering only queued sequences relevant to unfinished target checks when
available. It preserves the original per-case 80/128 effective goals and
fault-depth rules. If the old controller stopped at its 320-attempt cap, it
extends the existing conditional ceiling to 512 cumulative attempts. A
candidate target exception, a met effective budget, an active trial, an
empty queue, or an already exhausted 512-attempt cap blocks handoff. The
successor keeps the same shared `jvm-start.lock` and Java-process limit (no
more than four JVMs before a start) and raises its disk-free requirement to
10 GiB. Its own wall limit is 12 hours.

After copying only `successor.py` to the matching node1 directory, use the
old source hash as a guard:

```sh
python3 successor.py --preview --expected-old-sha256 824df96b2fbbcfeb2d29d444443a837f414d183f90e28fdf2789c8a07a40b93b
python3 -u successor.py --run --wall-seconds 43200 --expected-old-sha256 824df96b2fbbcfeb2d29d444443a837f414d183f90e28fdf2789c8a07a40b93b
```

Run the second command in its own persistent tmux session. The successor
holds `campaign.lock` continuously from verification through later trials.
It writes an atomic `successor-handoff-intent.json` before replacing the
checkpoint and an atomic `successor-handoff-receipt.json` afterward. These
record old/new checkpoint and source hashes, preserved list counts, scheduler
policy, the independent audit hash, and the final old trial's raw trace
hash. Repeating the command
after interruption resumes the recorded checkpoint, including any active
trial, without redoing completed trial directories.
