# HDFS-54 unchanged-JUnit supplement

This is a separate, graph-free experiment. It does not replace the existing
adapted HDFS-17897 known-bug control in `../result.json`.

## Terminal result

The unchanged embedded-cluster JUnit campaign reached its **80/80 effective
trial budget** on 2026-10-07 at 04:54:19 UTC. All 80 fault plans were applied
in their planned order to runtime-identified DataNodes and reached the exact
line-629 target after the final fault. The 80 trials applied 552 synthetic
checksum RPC exceptions in total; the deepest selected plan had nine faults.
The healthy JUnit took 17.72 seconds and the faulted JUnits took 1315.65
seconds combined, for **1333.37 seconds of measured JUnit time**. The wall
interval from campaign creation to completion was 02:34:00–04:54:19 UTC;
it includes handoff, replay, and scheduling pauses. The queue retained 512
untested plans when the 80-effective budget stopped the run.

Production JaCoCo feedback increased the union over the healthy seed by
1349 probe IDs, 295 method IDs and 498 branch-count slots; 20 faulted runs
added probes. Forty-four faulted JUnits reached line 629 with
`completed=false` and failed. Each was a nine-fault plan that exhausted all
nine distinct located DataNodes for the same file and block group. Trial 28's
identical plan reproduced this source-expected failure in a fresh fixture.
The original JUnit did **not** demonstrate the real stale cached encryption
key mechanism of HDFS-17897. The known-bug differential remains the
separate adapted control; this campaign found no new bug.

The [terminal audit](terminal/terminal-audit.json) checks every manifest,
ordered runtime trace, DataNode UUID, exact target event, JUnit result,
JaCoCo output and coverage union. The [per-trial ledger](terminal/trial-ledger.csv),
[raw evidence index](terminal/terminal-evidence-index.json), and
[compressed final checkpoint](terminal/terminal-campaign-state.json.gz)
are archived here. Full raw JUnit logs, traces and JaCoCo `.exec` files stay
under `/users/ZhenyuLi/hdfs54-original-campaign/runs` on node2; their hashes
are in the index. The archived CSV uses LF line endings; the terminal audit
records hashes for both it and the raw node2 CSV. The HDFS-54 tmux and JVM
exited naturally after trial 80.

## Source and workload identity

- Hadoop tag: `rel/release-3.4.3` (`9d50c688` locally).
- Unchanged JUnit: `org.apache.hadoop.hdfs.TestFileChecksum#testStripedAndReplicatedFileChecksum2[0]` from the released `hadoop-hdfs-3.4.3-tests.jar` (SHA-256 `08cb98dc77193afb196cb8b1f74108080c59bbcb3ae6430aca51bbfd004e9acb`).
- The original `@Before` builds a `MiniDFSCluster` with `dataBlocks + parityBlocks + 2` = 11 DataNodes, enables an erasure coding policy, and creates `/striped/stripedFileChecksum1`. The unchanged test obtains its checksum with `getFileChecksum`.
- Target: `FileChecksumHelper$StripedFileNonStripedChecksumComputer.checksumBlocks()` at source line 629. The bytecode overlay reports the boolean outcome of `checksumBlockGroup` at that exact conditional. A target record is valid only for the original file and after the final applied fault.

Only released production class bytecode is overlaid. The overlay records four
native application-level checksum RPC points (`connectToDN`, send
`BLOCK_GROUP_CHECKSUM`, read response, check response status), a generic
`IOException` catch at line 669, and the line-629 target. Each fault plan uses
`file, blockGroup, DataNode role, I/O site, occurrence, exception type`.
Runtime trace also records the actual DataNode UUID and block ID, but the plan
uses stable roles so it can match a fresh MiniDFSCluster. Four injected
exceptions are available: `IOException`, `EOFException`,
`SocketTimeoutException`, and `InvalidEncryptionKeyException`.

The first node2 healthy pilot passed the exact unchanged JUnit once in 17.72
seconds. It observed all four checksum RPC points, one line-629 target check
with `completed=true`, and 28,723 production JaCoCo probes. Its raw evidence
is at `/users/ZhenyuLi/hdfs54-original-campaign/runs/healthy-01` on node2.
The first strict fault pilot passed the same original JUnit in 17.57 seconds:
the one planned `IOException` at `CONNECT_L686`, DN role 0, was matched and
applied once. The trace then shows the line-669 `IOException` catch, checksum
RPC on DN role 1, and the same file's line-629 target check with
`completed=true` after the fault. It covered 28,727 production probes, four
more than the healthy seed. The raw directory is
`/users/ZhenyuLi/hdfs54-original-campaign/runs/trial-0001-01f09073125e7810-r0`.
The first checkpoint reported 1 effective trial and 31 queued mutations.
After its node1 handoff, a second strict trial finished in 21.065 seconds:
two ordered `CONNECT_L686` `IOException` faults matched and applied on
distinct DataNode roles 0 and 1 for the same block group. The production
catch at line 669 followed each injection. Role 2 served the request, and
the same file's line-629 target evaluated `completed=true` after the second
fault. The unchanged JUnit passed. It covered 28,883 probes, with 156 probe
tokens new to the prior global coverage set. The healthy and two fault runs
together cover 28,885 distinct production probes, 162 more than the healthy
seed. At that handoff boundary the node1 checkpoint reported **2/80
effective**, 2 attempts, 46 queued plans, and no in-flight plan. See
[`node1-trial2-receipt.json`](node1-trial2-receipt.json). The node2 copy was
paused at 1/80 until reconciliation.

## Campaign

`campaign.py` seeds one fault at each observed I/O point and then adds one
ordered fault at an observed point after the prior fault. It keeps only plans
whose fault order actually matched and whose target was reached after the
last fault as effective. The queue scores new I/O roles/sites, production
JaCoCo probe/method/branch-count gain, execution time, fault count, and wait
time. Every run gets a fresh JUnit MiniDFSCluster. `campaign-state.json` is
written atomically, `trial-ledger.csv` records time and outcome, and individual
trial directories retain trace, log, JaCoCo execution data, coverage tokens,
plan, and manifest. The campaign can resume without repeating completed
plans. The initial budget was 80 effective trials with at most 8 faults per
plan. After 22 effective trials, a case-specific source requirement raised
the cap to **10 faults within that same 80-effective budget**. The original
default RS-6+3 block group has nine located DNs; line 629 can become false
only after all nine checksum attempts fail. The old max-8 cap cannot reach
that state through one I/O fault per DN. Trial 23's already completed raw
JUnit was reconciled once at a post-JUnit checkpoint boundary; no effective
counter or plan was reset. The updated scorer prioritizes untested DN role ×
I/O site × exception families, distinct roles and depth up to nine, while
retaining production coverage and bounded waiting credit. See
[`max10-boundary-receipt.json`](max10-boundary-receipt.json). The separate
128-effective extension remains conditional on feedback. An attempt cap
keeps nondeterministic misses bounded.

The historical handoff procedure was: after node2's owner released its JVM slot, reconcile the node1
2/80 checkpoint and trial-2 evidence onto node2, verify both trial IDs and
the 46-plan queue, and then clear the node2 pause marker. Only then use
`bash /users/ZhenyuLi/hdfs54-original-campaign/resume_node2.sh`. The
launcher refuses an active Solr 36/37 session or another JVM and starts
`hdfs54_original_80` in tmux at lower CPU priority. The campaign must read
the reconciled 2/80 checkpoint and avoid repeating either completed plan.
The direct command, for inspection, is:

```bash
cd /users/ZhenyuLi/hdfs54-original-campaign
python3 campaign.py --runs /users/ZhenyuLi/hdfs54-original-campaign/runs \
  --effective-budget 80 --max-faults 10 --attempt-cap 320
```

### Optional node1 one-trial handoff

An offline copy of the same 20 MB campaign is staged at
`/users/ZhenyuLi/hdfs54-original-campaign` on node1. Both copies had
`campaign-state.json` SHA-256
`8728827521d8d650325f9801add8d15ba32dd38e3b458860f0ce1029ed256cf8`
when copied: effective 1, attempts 1, queue 31, `in_flight=null`. The
unchanged Hadoop test JAR also has the same SHA-256 on both hosts. Scratch,
ports, and run directories are local to each host; node1 had 32 GiB disk
and 55 GiB available RAM at staging time.

The node1 path was reserved for **one next queued trial** after SOLR-13
released its node1 slot and HDFS storage actor-V2 paused calibration. Running
`reserve_node1_pilot.py` from node0 verified both checkpoint copies and
absence of either HDFS-54 tmux, created a node2
`runs/.node1-pilot-active` marker to block `resume_node2.sh`, then writes the
node1 `runs/.node1-pilot-lease.json`. Any partial reservation fails closed;
inspect both marker files before retrying.
`resume_node1_pilot.sh` refused to run without that lease, validated the
unchanged 1/80 checkpoint and resource headroom, checked that SOLR-13 and
actor-V2 tmux sessions had exited, and started tmux
`hdfs54_original_node1_pilot` with `campaign.py --once 1`. It consumed the
next queued plan as trial 2; completed trial 1 was not rerun. The pilot ran
04:11:58–04:12:43 UTC. Its own measured JUnit duration was 21.065 seconds.
HBase-17's overlapping original JUnit r055 passed in 55.65 seconds with
postfault target, within its prior 49–57 second band. Node1 HDFS-54 tmux/JVM
exited, and the node1 slot returned to actor-V2 calibration. Node2's original
checkpoint remains unchanged behind `runs/.node1-pilot-active`. Reconcile
trial 2 and its updated checkpoint before clearing that marker. Never resume
both copies at once.

### Guarded node1-to-node2 handoff

From node0, `handoff_node1_trial2.py` compares both checkpoint hashes, the
ordered trial IDs, queue and lease. A read-only invocation prints the state.
Its `--stage-only` mode copies node1 trial 2, its two-fault plan, the ledger,
and the updated checkpoint into node2 `runs/.node1-trial2-handoff/`, checks
the raw trace/manifest/JaCoCo/log hashes, and leaves node2's **1/80** active
checkpoint and pause marker untouched. This stage was completed while the
HBASE-32 owner used node2 for an independent replay.

Once that owner explicitly releases the node2 JVM slot, run:

```bash
python3 .study-repairs/unit-test-pivot/cases/HDFS-54/original-junit/handoff_node1_trial2.py --apply --owner-released
ssh -i ~/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes ZhenyuLi@node2 \
  'bash /users/ZhenyuLi/hdfs54-original-campaign/resume_node2.sh'
```

`--apply` refuses an occupied JVM slot, verifies the staged artifacts again,
installs trial 2 and the 2/80 checkpoint, and removes the pause marker last.
The updated node2 launcher also refuses any checkpoint without both original
trial IDs in order, so a manual marker removal cannot replay trial 2. Check
the resulting tmux `hdfs54_original_80` and ledger after launch. Keep the
known-bug adapted control separate from this original-JUnit budget.

The HBASE-32 owner explicitly released node2 before `--apply`. The handoff
verified both checkpoint hashes and the staged raw-file hashes, installed
the 2/80 state, cleared the node2 pause marker, and retired the completed
node1 one-trial lease. The guarded launcher started persistent tmux
`hdfs54_original_80` from **trial 3**. Its first plan
`2e22b789974f74ab` finished in 17.233 seconds with three ordered faults
on three distinct DataNode UUIDs, unchanged JUnit pass, and the exact
postfault target `completed=true`; it added one production JaCoCo probe.
See [`node2-handoff-receipt.json`](node2-handoff-receipt.json). The campaign
continues under tmux, and its node2 `campaign-state.json` and
`trial-ledger.csv` are the live source of progress.

Trial 28 (`e080d9f78ce80f65`) applied nine `IOException` faults on nine
distinct located DNs for the same block group, then observed exact line 629
`completed=false` and original JUnit failure. The raw trace and released
source show the expected outcome when **all** checksum sources fail. A fresh
unchanged-JUnit replay of the identical plan again applied 9/9 faults and
reached the same false branch and `PathIOException`. This is a separate
target-false observation, not evidence of the stale-key mechanism or a new
bug. See [`trial28-source-review.md`](trial28-source-review.md).

### Queue refinement after trial 52

The first 52 original-JUnit trials were retained exactly as executed. By
trial 52, the queue had repeatedly selected nine-fault plans that disabled
all nine located DataNodes; their line-629 false outcomes are the expected
result of exhausting checksum sources, as confirmed by trial 28's clean
replay. At the completed trial-52 JUnit boundary, the campaign was paused
with its manifest and JaCoCo data intact. The revised score groups these
terminal plans by file, block group, and ordered DataNode-role × I/O-site
path, ignoring synthetic exception subtype. After two effective false
outcomes from one such path, further plans from it lose 1200 score points.
This retains deep-sequence sampling while giving other RPC sites, roles and
coverage-bearing seeds a chance within the same 80-trial budget. The
completed-trial count and checkpoint were preserved, and trial 52 was
summarized once from its existing manifest on resume. See
[`scheduling-boundary-receipt.json`](scheduling-boundary-receipt.json).

The first refinement distinguished full ordered role/site paths. Changing
an earlier RPC site still produced many nine-DN terminal variants: through
trial 62, 32 effective plans had the same all-nine-DN false outcome. A second
completed-JUnit boundary at trial 63 added a broader family score. Once at
least 12 strict 9/9 false outcomes exist for the same file, block group and
set of nine DN roles, another nine-fault plan loses 1200 points. The penalty
does not apply when its parent gained new production coverage or when the
plan contains an untested role × I/O-site pair. The first post-boundary new
plan was depth eight. Trial 63 was summarized once from its already complete
manifest; prior evidence and the 80-effective budget stayed intact. See
[`scheduling-second-boundary-receipt.json`](scheduling-second-boundary-receipt.json).

## Interpretation limit

The original JUnit enables block access tokens but does not set up an expired
data encryption key. A synthetic `InvalidEncryptionKeyException` at a checksum
RPC explores the line-669/629 response path; it does not demonstrate an actual
stale DataNode `allKeys` state. That state and the known HDFS-17897 differential
are evidenced by the separate adapted control. A target `completed=false`
after fault is a candidate observation until its source and replay are
reviewed; it is not automatically a new bug.
