# HDFS-34/35 actor-qualified base-budget review

The unchanged Hadoop 3.4.3 `TestDFSStartupVersions#testVersions` JUnit
passed in two fault-free MiniDFSCluster seeds (37.944 and 41.562 seconds).
Both used overlay digest
`ec5a27c482919e86eb3eb82805abd44a9a32af45dcd6d89781e2b8178d91df30`.
Each selected guard was reached on a bound DataNode startup episode, slot,
and configured storage directory. The shared receipt had 91 stable exact I/O
selectors. RPC faults also required the actor's raw NN0 endpoint; file faults
required its storage volume. No historical coarse-actor trial was imported.

The shared campaign ended at 2026-10-07 07:58:19.924120 UTC with 167 distinct
fault plans, all 167 injected in exact order. The maximum plan depth was eight
exception faults. The original JUnit exited 0 in 161 runs and 1 in six runs.
The independent `startup_terminal_raw_audit.json` verified the raw fault,
target, actor, endpoint, volume, JaCoCo, and checkpoint receipts with zero
issues. Its terminal checkpoint SHA-256 was
`abe6cd94707ce139a8259739d7c7830c4c70bac4e03eebdacb82f7c59eb14185`.

| Case | Exact production guard | First 80th effective plan | Strict plans in prefix | Target throws in prefix | New target signatures |
| --- | --- | --- | ---: | ---: | ---: |
| HDFS-34 | `DataStorage.doTransition`, stored namespace ID vs NameNode namespace ID, source line 744 | `15ec1e757b9ff4205fba`, 07:58:19.924 UTC | 167 | 8 | 0 |
| HDFS-35 | `DataStorage.doTransition`, stored cluster ID vs NameNode cluster ID, source line 752 | `01da1210a3584837ebc2`, 07:56:51.171 UTC | 166 | 0 | 0 |

HDFS-34's eight postfault `IOException`s all occurred with stored namespace ID
`Integer.MIN_VALUE` in startup episodes 6, 7, or 8. Their actor, storage
volume, check site, operand, branch outcome, and exception class match **both**
healthy seeds. The source test creates this incompatible VERSION state and
expects the DataNode startup to be rejected; the first occurrence has a
separate source and raw-trace review in `hdfs34_expected_rejection_review.md`.
The six JUnit exit-1 trials remain recorded as workload outcomes, not selected
new target exceptions.

The first 80 effective HDFS-34 trials exercised six logical startup actors
(episodes 3–8); HDFS-35 exercised nine (episodes 1, 9–14, 21, and 22).
Relative to the admitted healthy coverage corpus, HDFS-34 gained 38 production
branch IDs, 80 lines, 11 methods, and 83 JaCoCo probes. HDFS-35 gained 43
branch IDs, 79 lines, nine methods, and 80 probes. Neither case gained a
branch or eligible I/O family in its last eight effective trials, so the
conditional 128-effective/10-fault extension did not activate.

The first 167 shared fault JUnit subprocesses took 11,122.923 seconds; the
first 166 took 11,040.150 seconds. Including the two healthy seeds gives
11,202.429 seconds for HDFS-34 and 11,119.656 seconds for HDFS-35. This is
shared original-JUnit time attributed separately to each check and **must not
be summed across cases**; controller pauses and overhead are excluded. The
corresponding effective-trial JUnit time was 5,529.923 and 5,438.934 seconds.

Both checks have completed their actor-qualified base budgets. There is **no
observed new bug** at either exact guard. The shared checkpoint also contains
opportunistic HDFS-22/23/25 observations beyond their previously frozen 80
effective trials; those checks remain at their original completed result and
are not recounted. Raw evidence is on node1 under
`hdfs-storage-actor-v2/evidence/startup-constructor/`.
