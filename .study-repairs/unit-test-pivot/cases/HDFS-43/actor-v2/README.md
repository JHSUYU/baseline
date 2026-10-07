# HDFS-43 actor-aware original-JUnit replacement

## Evidence decision

The earlier 80 main and 128 supplementary trials remain archived under
`../independent/`. Their `FAULT_APPLIED` records contain only a normalized
thread name and a global `Client.getRpcResponse` ordinal. Their target check
contains file path and lengths but no block ID or request key. A later target
check cannot be tied to a particular client RPC or DataNode from those fields.
Historical `78/80` injection and `49/80` postfault-target counts therefore do
not qualify for this replacement.

The released Hadoop 3.4.3 source at `FSDirTruncateOp.java:113-117` compares a
second requested truncate length with the length already under recovery. The
unchanged `TestFileTruncate#testTruncateTwiceTogether` intentionally requests a
different length and expects `AlreadyBeingCreatedException`; that exact throw
is the healthy behavior, not a new bug.

## V2 identity and scope

Two fresh invocations of the original MiniDFSCluster JUnit calibrate the
target and observed I/O before fault trials. Both original methods still
perform all their operations and assertions. Case-local source overrides add
only tracing and an ordered exception gate:

- `Client.getRpcResponse` after request send records client ID, call ID,
  destination, and a semantic context supplied by the truncate or DataNode
  block-report translator. The fixture records the actual NameNode RPC port;
  only I/O whose physical destination port matches it can receive the `nn0`
  selector and qualify as a strict fault.
- The fixture maps `MiniDFSCluster.getDataNodes()` indices to physical UUIDs.
  A block-report selector includes the DN role, UUID in the event, and block ID.
- `FSDirTruncateOp.truncate` records path, last block ID, truncate block ID,
  both lengths, branch outcome, phase, and server-side client ID/call ID.
- The same source records the file's last block at truncate entry. A fault on
  a truncate RPC qualifies only when that server-side entry has the same
  request key and resolves to the later target block. Block numbers may differ
  across fresh MiniDFSCluster runs; the link is checked within each run.
- The original JUnit has phase markers before the first and second truncate.
  Target eligibility requires the same file/block after the last applied
  fault, in the second-truncate phase. A second-truncate RPC requires the exact
  client/server request key; a prior truncate requires the same file, block,
  and request key; a DataNode block report requires the same block and UUID-to-role
  mapping. Ambiguous I/O is observed but not selected.

JaCoCo feedback is exported only for classes analyzed from the released HDFS,
HDFS client, and Hadoop common JARs plus the four production overrides. Probe
and JUnit classes are excluded. `METHOD` and `PROBE` are exact identities;
`BRANCH_UNIT` records covered branch counts per source line and does not label
which edge was taken. The target branch outcome is logged explicitly.

The healthy coverage and I/O baseline is the union of both fresh runs. The
new campaign has its own checkpoint and atomic per-trial result. It starts
at 80 effective trials with at most 8 ordered faults; production coverage or
a stable I/O-family gain in effective trials 73-80 extends it to 128 effective
trials and 10 faults. Attempt safety caps are 320 and 512 respectively, and
queue exhaustion is reported if the observed I/O cannot supply the effective
budget. The previous trials are excluded from both the budget and coverage
union. An exact target outcome outside the original expected exception stops
the campaign for same-selector replay and source review.

Before the healthy JUnit and each fault trial, the node2 controller checks
that adding one Java process stays within five active Java processes and that
at least 10 GiB is free. A closed gate leaves the checkpoint intact for a
later resume; the case owner still coordinates the cluster slot with other
node2 owners.

`campaign/resume_until_terminal.py` is the tmux entry point for the full
campaign. It resumes the same checkpoint after a temporary node2 resource
gate pause, and exits for a candidate or a terminal budget decision.

After trial 18, the original coverage/I/O score had selected DN block reports
for every last fault while client truncate RPC plans remained queued. At that
complete boundary, `campaign/migrate_api_diversity.py` preserved the completed
trials, queue, and seen selectors, then reserved every fourth subsequent
selection slot for a queued client truncate RPC. All other slots keep the
original score and waiting-age ranking. The before/after checkpoints and
receipt record the change; strict injection, actor matching, oracle, and
coverage admission rules remain the same.

At the complete trial-40 boundary, 25 of 40 plans had strictly applied and
22 retained the same file/block target after the last fault. The independent
auditor reported zero errors. Several high-scoring depth-2/3 DataNode plans
were partial because a subsequent block-report RPC did not recur, while the
client truncate quota trials had strictly applied and retained the target.
`campaign/migrate_client_quota_v2.py` therefore reserved every second
selection slot for a queued client truncate RPC starting with trial 41. The
other half still uses the original coverage/I/O and waiting-age score. Its
before/after checkpoint snapshots, receipt, and SHA-256 manifest of all 40
trial results, raw traces, manifests, selector plans, and the ledger verify
that no completed trial, queued selector, or raw evidence changed. The
strict-injection, actor, target, oracle, and coverage rules are identical.

At trial 110, the independent raw auditor reported 110 attempted, 69 strict,
65 effective, and zero errors. The remaining observed-I/O queue held 14
two-fault and 8 three-fault truncate plans; the score preferred depth three,
but several recent deep plans only partly applied. At this complete boundary,
`campaign/migrate_shallow_first.py` preserved every completed trial, queued
plan, seen selector, raw trace, manifest, result, plan, and ledger, then chose
the minimum queued depth before applying the original coverage/I/O score and
waiting age within that depth. The three-fault plans remain queued for later
selection. The migration receipt records before/after checkpoint SHA-256,
raw-artifact manifest SHA-256, and production coverage/I/O counts. No target,
identity, strict injection, coverage admission, or bug oracle rule changed.

## Final result

The six released source files were copied into this case and match the clean
Hadoop 3.4.3 checkout. The V2 source overrides compiled with Java 8. The
synthetic, cluster-free `offline_smoke.py` passed its ordered selector and JSON
trace checks. Coverage exporter compiled. Two fresh original MiniDFSCluster
JUnit healthy calibrations passed and recorded the exact target guard,
expected `AlreadyBeingCreatedException`, and relevant I/O. The actor-aware
campaign ran from a checkpointed controller in node0 tmux
`hdfs43_actor_v2_full`; each original JUnit ran over SSH in the coordinated
node2 slot. It stopped at **125 attempted / 84 strict / 80 effective** trials
after 4 strict trials lost the same-actor target and 41 plans only partly
matched. The 125 plans requested 279 faults; 215 matched and applied. The
largest tested sequence had four ordered faults, within the maximum-eight
budget. Across the two healthy calibrations and fault trials the controller
recorded 4,172.592 seconds. Both healthy JUnit runs passed.

All 80 effective trials reached the exact `FSDirTruncateOp.truncate:113-117`
guard after their last applied fault on the same file and block. All 80
reached the expected `AlreadyBeingCreatedException`; no new target outcome
was observed. The released source returns for an equal second truncate
length and throws this exception for a different length while the block is
`UNDER_RECOVERY` (`FSDirTruncateOp.java:113-118`). The original JUnit
explicitly intercepts the latter exception
(`TestFileTruncate.java:279-282`). Of the 80 effective trials, 25 original
JUnit methods exited zero; the other 55 failed on the fault injector's
intentional client `truncate` response exception. All 55 raw JUnit failure
summaries were checked and have the same injected response selector. These
JUnit failures are retained in the manifest but are not new target bugs under
the target-exception oracle.

Accepted feedback added 21 production method IDs, 77 per-line branch-count
units, 170 JaCoCo probe IDs, and three stable I/O families. JaCoCo is
collected for the entire JUnit execution, so a new ID alone does not prove
that a fault causally executed a method; the explicit target branch and actor
linkage come from runtime events. Effective trials 73-80 added no production
coverage ID or stable I/O family, so the predefined extension to 128
effective trials did not activate. The previous 80 main and 128 supplementary
trials without physical actor identity remain excluded.

`campaign/final-audit.json` is the independent 125-trial replay of raw
selectors, physical NN/DN identities, file/block target linkage, coverage
IDs, and the ledger; it reports zero errors. `campaign/final-summary.json`
records the totals and extension decision. The 507-file
`campaign/raw-trace-selector-evidence.tar.gz` preserves healthy/trial trace,
selector plan, manifest, trial result, checkpoint, and ledger. Its SHA-256 is
`94a2fa634572e1f3b9edf8a703c2be6539526e1f4ecb83c6b8e486c7a1e9d11d`.
`campaign/final-artifact-manifest.json` lists absolute local paths and
SHA-256 hashes for all 888 raw artifacts, including 127 JaCoCo exec files
and their exported coverage. The exporter command is
`python3 system-test/run_coverage.py --exec <trial>/jacoco.exec --output <trial>/coverage.tsv`.
The released Hadoop 3.4.3 JARs and case-local production overrides are
identified by `system-test/build-probe.json`. The tmux controller and its
node2 JUnit JVM had exited when the final audit ran.
