# HDFS-19 independent coverage and I/O campaign

## Selected check and original workload

- System: released Apache Hadoop HDFS 3.4.3.
- Check: `BPOfferService.processCommandFromActive(DatanodeCommand, InetSocketAddress)`, source line 768 (`getBlockPoolId().equals(bp)`) under `DNA_FINALIZE`; an unequal block pool ID raises the `AssertionError` at line 769. The probe records the boolean evaluation and the exact throw site separately.
- Workload: original `org.apache.hadoop.hdfs.TestDFSFinalize#testFinalize` JUnit. It stages `current` and `previous` NameNode/DataNode directories, starts `MiniDFSCluster`, finalizes the cluster, triggers block reports, and repeats with and without old directories for one and two storage directories. It is run unchanged from the released `hadoop-hdfs-3.4.3-tests.jar`. The binary test JAR omits Maven's test resource `hdfs-site.xml`; `run_original.py` loads that resource from the same released `hadoop-hdfs-3.4.3-test-sources.jar`.

## Independent instrumentation

`independent/PatchHdfs19.java` uses ASM to instrument the four released production classes `BPOfferService`, `BPServiceActor`, `DataStorage`, and `BlockPoolSliceStorage`. There is no GraphChecker runtime or causal graph. `independent/CoverageHdfs19.java` extracts production JaCoCo probe, method, and covered branch-count feedback. `independent/Hdfs19Probe.java` records runtime identities and applies a planned `IOException`, `EOFException`, or `SocketTimeoutException` immediately before a selected I/O call.

The observed I/O scope is the block-report RPC and the two finalize storage renames. An I/O identity contains marker, concrete call site, normalized block-pool or file source, and ordinal within that identity. Full physical resource paths remain in the trace for audit. Two independent healthy runs reached the check nine times each, observed the same five I/O families, and passed the original JUnit. A one-fault smoke run matched and applied its requested first block-report `IOException`, reached the target again after that fault, and passed JUnit.

The released JAR hashes, both healthy trace summaries, and the smoke replay are recorded in `independent/bootstrap-evidence.json`.

## Campaign and result criteria

`independent/campaign.py` mutates observed fault sequences, records each run in `independent-trial-ledger.csv`, and atomically checkpoints the queue and completed trials in `independent/campaign-state.json`. Initial budget: 80 trials, up to eight faults per sequence. If the final valid trials still discover production method/branch-count coverage or I/O families, it extends to 128 trials and ten faults. `independent/run_original.py` executes each trial in a fresh scratch directory.

When selecting a sequence, the controller favors I/O families whose earlier strict trials retained this same target check after the final fault. Every fifth selection explores other families, including the finalize file renames. This uses only runtime target, I/O, and coverage feedback.

A sequence is strict only when all requested faults match and apply in order at their exact runtime identities. It contributes feedback only when the selected target check runs after the last fault. A target-site `AssertionError` after the last fault is a candidate for replay and source review; it is not automatically a confirmed new bug. If the fault prevents the target from running, that trial is recorded but does not count toward target feedback. The live outcome and elapsed time are in `result.json` and the trial ledger.

Resume the tmux campaign after an interruption with `python3 independent/campaign.py` from this case directory. Its lock and `active` checkpoint preserve the uncompleted sequence for replay.
