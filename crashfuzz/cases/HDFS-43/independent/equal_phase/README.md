# HDFS-43 supplementary equal-branch campaign

Original Hadoop 3.4.3 `TestFileTruncate#testMultipleTruncate` is the workload. Its healthy run has four exact `FSDirTruncateOp.truncate#L113-IFNE` visits, all equal, and zero target exceptions.

The supplementary phase completed 128 trials in 3396.968 attributed JUnit seconds; 119 strict injections and 41 target-retaining trials. Post-fault target exceptions: 0; bug mark: `none`; status: `quality_complete_supplementary`.

Post-fault equal/different branch outcomes: `{"FSDirTruncateOp.truncate#L113-IFNE": {"different": 0, "equal": 148}}`. Coverage gain: `{"branch_counts": 613, "lines": 1653, "methods": 270, "probes": 1494}`.

This phase has its own healthy seed, atomic checkpoint, raw trace, JaCoCo coverage, and per-trial ledger. It supplements the HDFS-43 checklist entry; it does not count as another completed check. The same case-local ASM overlay and unchanged original MiniDFSCluster JUnit are used. No GraphChecker graph, closure, or Docker workload is involved.

Source review: FSDirTruncateOp.truncate returns an idempotent result when a second request matches the length already being truncated. The unchanged TestFileTruncate#testMultipleTruncate reaches that equal branch four times and never throws AlreadyBeingCreatedException. A post-fault target throw is a candidate only; its requested and in-progress lengths and recovery state need replay and review.

Evidence: [result](equal-result.json), [trial ledger](trial-ledger.csv), [checkpoint](evidence/campaign-state.json), [healthy manifest](evidence/healthy/manifest.json).
