# HDFS-22/23/25 actor-qualified base budget review

The unchanged Hadoop 3.4.3 `TestDFSStartupVersions#testVersions` JUnit reached
all three exact guards in each of two fault-free MiniDFSCluster seeds. The
seeds passed in 37.944 and 41.562 seconds with the same overlay digest
`ec5a27c482919e86eb3eb82805abd44a9a32af45dcd6d89781e2b8178d91df30`.
Each seed reached HDFS-22 and HDFS-23 eight times and HDFS-25 six times, on
matching logical startup episodes, DataNode slots, and configured storage
directories. The healthy receipt has 91 stable exact I/O selectors across
the shared test. Every bound RPC selector additionally retains and checks
its raw NN0 endpoint; file selectors require the same DataNode volume.

The 88th distinct fault plan, `977d14ccdd619dcf9673`, finished at
2026-10-07 06:24:31.031633 UTC. At that checkpoint prefix, each of these
three cases first reached its base goal of 80 effective same-actor postfault
checks. All 88 plans had their requested faults injected in exact order; the
deepest sequence had eight exception faults. The 88 original JUnit attempts
had 82 exit-0 and six exit-1 outcomes under injection. The 80 effective
trials for each case saw zero target exceptions. The independent raw
`audit_checkpoint.py` found no actor, endpoint, storage, ordering, or coverage
receipt issue and no novel target-exception signature.

| Case | Exact production guard | Effective / base goal | Target throws | Active time for 80 effective attempts |
| --- | --- | ---: | ---: | ---: |
| HDFS-22 | `BlockPoolSliceStorage.doTransition`: stored namespace ID vs NameNode namespace ID, source line 396 | 80 / 80 | 0 | 5,693.632 s |
| HDFS-23 | `BlockPoolSliceStorage.doTransition`: stored block-pool ID vs NameNode block-pool ID, source line 401 | 80 / 80 | 0 | 5,693.632 s |
| HDFS-25 | `BlockPoolSliceStorage.loadStorageDirectory`: stored cTime vs NameNode cTime, source line 186 | 80 / 80 | 0 | 5,693.632 s |

The 88 shared JUnit attempts took 5,890.160 seconds in total. These times
are measured subprocess durations; the shared workload and its coverage must
not be summed across cases. Across the first 80 effective results, each case
gained 51 production branch IDs, 96 line IDs, 12 method IDs, and 101 JaCoCo
probe IDs relative to its admitted coverage corpus. None of the last eight
effective trials added a branch or eligible I/O family, so the conditional
128-trial/10-fault extension did not activate. The source test deliberately
constructs incompatible VERSION states and accepts corresponding startup
refusals; a JUnit exit-1 by itself does not establish a coordination bug.

This is a completed **base-budget check with no observed new bug** for these
three exact guards. The same shared campaign continues for HDFS-34/35, so
later opportunistic executions of HDFS-22/23/25 are retained in its live
checkpoint but are outside this frozen base-80 review. The raw evidence is
on node1 at `hdfs-storage-actor-v2/evidence/startup-constructor/`; the
historical coarse-actor case trials are not included in these counts.
