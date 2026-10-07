# HDFS-32 V3 timeout coverage review

The released `TestDeleteBlockPool#testDeleteBlockPool` actor-bound campaign
finished at 152 attempts, 135 exact injections, and 128 effective selected
target checks. The independent semantic audit found no errors or candidates.

Trials 46, 59, 93, 97, 126, 132, and 138 ended at the runner's 180-second
timeout (`junit_exit=124`). Each retained its original fault plan, driver
log, JUnit log, runtime trace, manifest, and zero-byte `jacoco.exec`. The
original runner only creates coverage text reports when JaCoCo data is
nonempty, so no `covered_probes.txt`, `covered_methods.txt`, or
`covered_branch_counts.txt` was produced for these seven trials. Their
checkpoint rows have no postfault target check, coverage gain, or new I/O
family; none contributes to the 128 effective denominator or novelty rule.

The versioned raw inventory requires coverage reports for every run with
nonempty JaCoCo data. For empty JaCoCo data it accepts only a matching raw
JUnit timeout and records that trial under
`coverage_unavailable_due_to_junit_timeout`. It hashes every file that
actually exists and never synthesizes coverage. The independent full inventory
then verified 1,519 raw files totaling 1,196,308,651 bytes with zero errors.
The terminal receipt carries the explicit seven-trial coverage limitation.
