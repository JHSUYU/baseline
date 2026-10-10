# Original-102 HDFS full queue: offline completion-rule audit

Source mirror: Apache Hadoop 3.4.3 commit
`9d50c6884666e794e45102260a4017bb31802e1b`, tracked-source digest
`825878fdb546b98f0c1c17339d83625e62fa0aadd5b76284a2640fac3926bef7`.
All checks below were static on node0. No JVM, fault trial, or full controller
was started for this audit. Existing v1 packages and outputs were untouched.

| Case | Ready case-local package | Static check | Current limit |
| --- | --- | --- | --- |
| HDFS-19 | `hdfs19-node2-full-stage-v2`, config `c2ca831aa086bba197597d4043840f5dd2d1854878f0ec4d9209608b113310c6` | PASS | New healthy seed must name the exact DataNode target and an eligible I/O door. |
| HDFS-20 | `hdfs20-node2-full-stage-v2`, config `e974331a20a4a5f3f323691a7164ba23a0b8d9b7ac922bc4f43e61b9c94551e5` | PASS | Heartbeat door to target path remains unverified. |
| HDFS-29 | `hdfs29-node2-full-stage-v2`, config `cc98fde3de231996ca23702f826a64027451ae2f17c4b97423cb8e801e1a74fa` | PASS | Original JUnit had a prior timeout; fresh named healthy seed required. |
| HDFS-30 | `hdfs30-node2-full-stage-v2`, config `29ba954473d182b858a7b1fa1ab5a17f169064cc34af14e8ead0ab166cbefafe` | PASS | Original JUnit previously reached the check with unknown actor; fresh named seed required. |
| HDFS-31 | Existing `hdfs31-32-node2-full-stage-v1`, config `1f361ef328caabc555bb1bca55257118b46c05e7a8c3ac79baf2796c56be5880` | PASS | Full config is ready offline; fresh seed pending. |
| HDFS-32 | Same package, config `43e282f536e3be34d543f1d4e18073464ab4ae992ea36350691217fa597ba0a0` | PASS | Full config is ready offline; fresh seed pending. |
| HDFS-33 | Existing `hdfs33-34-node2-stage-v1`, healthy config `af9fb92b46a16eb7ea41191adfb56ecf0caf5e03abcbc450495fe632d57b7f95` | Equivalent-source SHA PASS | Healthy-only; no case-local full config. Named target remains unverified. |
| HDFS-34 | Same healthy-only package, config `23babe4c59dd019115310b4ba8a9c76bd8df48ce8b7ece50e589c3ecd005363e` | Equivalent-source SHA PASS | Healthy-only; no case-local full config. Exact target and named actor remain unverified. |

The HDFS-19/20/29/30 v1 configs encoded a separate graph-path and offline
audit gate (`minimum_healthy_observed_path_doors=1`, nonempty observed graph
path, audit report required). Their v2 sibling configs set those three fields
to `0/false/false`. They preserve passing JUnit, exact nonthrowing target,
named node, and an eligible pretarget injectable I/O door. Each v2 runner
uses a new output directory and the same node2 HDFS source lock, so frozen
v1 output and SHA pins remain reviewable. The frozen fa5f Mallory core's
runtime healthy attestation checks named target region, exact catalog/class,
and an eligible pretarget door; it does not read those graph-quality metadata
fields as admission conditions. The v2 preflights pin the corrected fields.

HDFS-31/32 already encode graph path quality as an outcome and have full
80-trial, 3600-second, max-three-fault budgets. HDFS-33/34 currently have
only one-trial calibration configs. Their original node2 preflight requires
the node2 source root; the equivalent-source check here substituted the
byte-identical node0 `hdfs-lane2` mirror, verified the full tracked-source
digest, all handoff/runtime artifact hashes, static frontier, and config
shape. They need full configs only after the runtime healthy identity and
eligible-door evidence is known; graph-path quality remains an outcome.

For every full run, report Mallory's natural terminal status and actual
completed fault-trial count. A path gap or loss of the exact target in fault
trials is a measured outcome. A failed fresh healthy admission is reported
as such, with its zero fault-trial count; archived healthy seeds are not
substituted for the new run.

## Manifest SHA-256

| Package | Manifest SHA-256 |
| --- | --- |
| HDFS-19 v2 | `48e9c4f3f20b3dab04d87dd0aeb384dac3bb0d8a0977773280bd48469ddb5053` |
| HDFS-20 v2 | `e2231c3aa317bef43264276fc627a17a6d2be00ce1f121210f9047a5d063e0ed` |
| HDFS-29 v2 | `a22096f70b7dc9ac279991fb4d3b4df9721006575a4f59cddb9d159f8e0e9883` |
| HDFS-30 v2 | `dafbb1ed204034253f73ef99e4a9328e243cafc4d5de01b55a70c943ec226403` |
| HDFS-31/32 v1 | `c881b77aa7e52b553a33819a83f5cc75925e8dd6475525cb1d48701b157880fa` |
| HDFS-33/34 healthy handoff | `516f6ae03de342abe28c4479754d6afb3145ea0e9ef32fa46bd384d091ada29d` |
