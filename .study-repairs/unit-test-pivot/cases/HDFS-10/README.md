# HDFS-10: writer epoch check in `Journal.checkWriteRequest`

**Current 102-check status: quality_complete (independent recorder).** The 48
trials below remain historical evidence in `legacy-graph-result.json`. Their
exact I/O selectors contain GraphChecker `REGION.*` identities from prewoven
classes, including trials later run in discovery mode. They do not count as
the graph-independent runtime campaign.

## Independent replay (current)

The new `independent/` recorder runs the unchanged upstream
`TestQuorumJournalManager#testSingleWriter` through JUnitCore with its native
three-JournalNode MiniJournalCluster fixture. A case-local ASM 9.6 classpath
overlay reads original Hadoop 3.4.3 binaries and records the exact `IFEQ`
writer-epoch check in `Journal.checkWriteRequest`, its actual `IOException`
throw or normal return, `PersistentLongFile.set` writer-epoch file writes,
and `Client.getRpcResponse`. [Original and patched bytecode](independent/evidence/independent-overlay-checkWriteRequest-javap.txt)
pin the hook immediately before the original branch and throw. JaCoCo 0.8.15
supplies production method, line, branch-count, and exact probe feedback;
runtime-generated Mockito mock classes are excluded. No GraphChecker
prewoven class, runtime JAR, region skeleton, static I/O map, graph, or
closure is in this execution path.

The independent healthy original JUnit passed in **11.930 seconds**. It
reached the exact check six times with request epoch 1 equal to writer epoch
1, and observed 36 IPC responses plus three writer-epoch file writes. Two
fresh replays of `IOException` at `journalnode-0`'s writer-epoch write both
matched and applied, then recorded the exact guard seeing request epoch 1
versus local writer epoch 0 and throwing its declared `IOException`; the
original JUnit passed using the other JournalNodes. The exact fault, check,
and throw events from both runs are in [the smoke replay summary](independent/evidence/smoke-replays-summary.json). Reading
`Journal.checkWriteRequest` and `PersistentLongFile.set` confirms this is an
intended rejection after the local epoch write failed, so those throws are
recorded as **expected guard responses**, while any different target throw
remains a candidate for review.

The graph-independent campaign completed **80/80 trials** with an eight-fault
sequence ceiling. All 80 sequences applied in exact order; 66 reached the
target after the final fault. The maximum actual depth was **three faults**.
Thirteen post-fault target `IOException` events occurred in thirteen trials;
all matched the source-reviewed, expected writer-epoch rejection. Production
JaCoCo feedback gained **79 methods, 119 branch-count IDs, 329 probes, and
373 lines** over the healthy baseline. The 80 trial JUnit runs plus the
healthy JUnit took **1,330.213 seconds** in total. No new bug is marked.
The final eight trials added no production coverage or stable I/O family, so
the conditional 128-trial extension was not used. The per-trial times and
selectors are in [the independent ledger](independent/trial-ledger.csv),
with the atomic checkpoint in `independent/evidence/campaign-state.json` and
the checklist result in [result.json](result.json). The following sections
document excluded historical work and are not counted in this result.

## Source and original cluster test

The source is the clean Hadoop `rel/release-3.4.3` worktree, commit
`9d50c6884666e794e45102260a4017bb31802e1b`. At `Journal.java:514-522`,
`checkWriteRequest(RequestInfo)` first calls `checkRequest`, then compares the
request epoch to `lastWriterEpoch.get()`. A mismatch throws `IOException` with
the request and current writer epochs. The original class bytecode has the
comparison at offset 17 (`ifeq 77`), the throw at offset 76, and source line
520 on the exception message's second epoch read. The exact runtime branch is
`<org.apache.hadoop.hdfs.qjournal.server.Journal: void checkWriteRequest(org.apache.hadoop.hdfs.qjournal.protocol.RequestInfo)>#u7`.
[Source](hadoop-3.4.3/hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/qjournal/server/Journal.java)
and [original bytecode](original-Journal-javap.txt) pin the location.

The unchanged upstream `TestQuorumJournalManager#testSingleWriter` runs via
[the independent JUnit runner](independent/run_original.py) and JUnitCore. Its `@Before`
creates three JournalNodes; its `@After` and `@Rule` execute. It writes and
finalizes edit segments 1–3 and 4–4. The healthy original JUnit passed, with
six executions of branch `#u7` on the three JournalNodes. All compared request
epoch 1 to local writer epoch 1 and returned normally. The stable selected
call is jn2's second `Journal.journal` request for segment 4, first transaction
4, one transaction; it was reached once in the healthy trace.

## Fault sites and trace validation

The IPC probe records the original `Client.getRpcResponse` call, whose method
declares `IOException`. Its exact selectors identify response occurrence,
source, hit ordinal, and `IOException`, `EOFException`, or
`SocketTimeoutException`. The file probe has one patch at the
`PersistentLongFile.set` call to `writeFile(File,long)` (declares
`IOException`) and one patch at the `AtomicFileOutputStream(File)` constructor
(declares `FileNotFoundException`). Its [bytecode proof](epoch-door/patched-javap.txt)
shows each inserted call. The original healthy file run observed one writer
epoch write call and one constructor open per JournalNode. Every trial starts
with a fresh test data directory, temporary directory, and trace directory;
ports are chosen independently by the original MiniJournalCluster.

The runners now use trace mode `discovery` with no region skeleton property.
IPC trials 1–30 and the completed file phase used the earlier `region-state`
recording setting; IPC trials 31 onward use discovery. This setting only
affected low-level event recording in this case; no static analysis,
aggregation, or closure planning was run.
The [mode validation](discovery-validation.json) passed the same original
JUnit with and without one exact IPC fault. All 108 healthy I/O selector
identities, the selected target call, 140 healthy method/branch coverage IDs,
the single applied fault ID, and its 141 coverage IDs were identical between
the prior runtime trace setting and discovery. Completed selectors were not
rerun by the resumed campaign. The case consumes only call, branch, fault,
source, and coverage events; there is no graph analysis or graph-based result
decision.

## Bounded trial campaign

The historical IPC campaign chose observed response selectors, ran
one to four exact exceptions per trial, records method/branch and new I/O
feedback, and checkpoints after every attempt. A multi-fault plan is valid
only when all selected faults match and apply. Missed plans and trials that
lose the target are retained in the ledger and excluded from the effective
count. The historical file campaign used the observed first writer
epoch write on each node with legal exception types. The consolidated
[ledger](trial-ledger.csv), [result](result.json), and both checkpoint files
retain per-trial selector, duration, applied evidence, target-after outcome,
JUnit result, and coverage.

The six legal file trials precisely matched and applied. They include a clean
replay of the jn2 `IOException` writeFile-call selector, a second node with
that exception, and all three nodes with `FileNotFoundException` at the
constructor. Each failure left the affected node's `lastWriterEpoch` at 0
while a later request carried epoch 1. Branch `#u7` took its mismatch edge
and threw the declared `IOException` once in each trial. The original JUnit
completed successfully each time because the other JournalNodes supplied a
write quorum. The affected logger was marked out of sync and retried after
the next log roll; the selected final jn2 call eventually saw epochs 1 and 1.

| Phase | Attempts | Effective exact faults with target afterward | Target guard `IOException` | Original JUnit failures |
| --- | ---: | ---: | ---: | ---: |
| IPC response | 53 | 42 | 0 | 1 effective; 11 unmatched attempts also failed |
| Writer epoch file I/O | 6 | 6 | 6 intended guard responses | 0 |

The 11 unmatched IPC plans failed before all selected faults could apply and
are excluded. The single effective JUnit failure is trial 26: all three IPC
faults applied and the selected target returned normally, but later
`QuorumOutputStream.flushAndSync` raised `QuorumException` after two of three
response paths failed. This is the original write quorum threshold, not a
failure of the target guard. Combined healthy production method/branch
coverage was 133 IDs; trials reached 149, a gain of 16. The full case elapsed
time, including source/setup, both healthy runs, both trial phases, and review,
is recorded in `total_elapsed_seconds`.

An earlier exploratory file probe injected a general `IOException` at the
constructor. That exception exceeds the constructor's declared
`FileNotFoundException`, so those attempts are excluded from the effective
trial count. Their traces remain under `epoch-trial-*` and
`epoch-trials/checkpoint.json` for audit. The corrected `epoch2-trial-*`
evidence is the file phase used in [result.json](result.json).

The source review identifies the observed mismatch exception as the intended
guard response after a failed writer-epoch write. The unchanged test tolerated
the single-node failure, and clean replay reproduced the same transition.
`bug_mark` is `none`; a failed write by itself is not evidence of a new
coordination bug.

## Reproduction

Use [independent/run_original.py](independent/run_original.py) for the unchanged
JUnit and [independent/campaign.py](independent/campaign.py) to resume only
uncompleted graph-free trials. The obsolete graph-runtime runner and controller
source has been removed; historical traces, selectors, checkpoints, and logs
remain for provenance and are excluded from current totals. No Docker was used.
