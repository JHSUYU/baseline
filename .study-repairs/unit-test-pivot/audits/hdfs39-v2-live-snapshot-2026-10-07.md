# HDFS-39 actor V2 independent live snapshot

Audited at 2026-10-07 10:21 UTC. This is a read-only snapshot of the running campaign, not a terminal classification.

- node1 checkpoint: `hdfs39-rpc-actor-v2/evidence/campaign-v2/checkpoint.json`, SHA-256 `c72019440959d8446732cd066bde267b9a3855c6661cba085f7f559a5a6c3d16`; 34 completed trials and no in-flight trial at the snapshot.
- Audit program: `audits/hdfs39-live-raw-audit.py`, SHA-256 `93a8ccafc11a38330b0e90991ffa6f37a5b7ef2a4539983509931d0209c40dee`.
- Recomputed independently from each immutable plan, original `TestFileAppend#testMultipleAppends` JUnit manifest/class SHA, trace and JaCoCo hashes, runtime four-DN UUID/BP/NN-peer binding, and same `/testMultipleAppend/foo` block `1073741825` target guard after the final applied fault: **15/34 fully applied, 9/34 effective**. The code coverage union has **46,104** IDs and the relevant actor-aware I/O union has **11** families. Both equal the checkpoint after rebuilding them from the two healthy seeds and effective raw trials. No postfault `RetriableException` candidate or disagreement with a trial result was found. Audit errors: **0**.
- Invalid or unmatched trials remain in the attempt denominator and contribute no effective coverage. For example, `trial-0001-attempt-01` has zero applied faults and a pre-fault target exception; it is correctly excluded from the postfault candidate count.

The campaign must continue toward its applicable effective budget. This receipt does not validate trials added after the checkpoint hash above or classify any future target exception.
