# HDFS-43: original cluster-test selection

The selected check is in Hadoop 3.4.3
`FSDirTruncateOp.truncate` around source lines 105–119. If the last block is
`UNDER_RECOVERY` and has a truncate block, it compares the new request length
with the in-progress truncate length. Equal lengths return
`TruncateResult(false)`; different lengths throw
`AlreadyBeingCreatedException`.

The proposed original `TestFileTruncate#testTruncateTwiceTogether` starts an
embedded cluster, writes a file, delays DataNode recovery, issues one truncate
from a second client, then deliberately requests a different length. The
test **expects** the selected exception and verifies that recovery preserves
the first requested length. A selected exception in this workload is therefore
normal behavior, not a new bug by itself.

`TestFileTruncate#testMultipleTruncate` is an additional original embedded
cluster workload to calibrate: it immediately retries each truncate with the
same length and expects an idempotent result, potentially covering the equal
branch without the selected exception. Neither workload is yet counted as a
current-method fault trial. The next step is case-local ASM/Jacoco healthy
calibration to measure exact guard and branch visits before selecting I/O
fault points. The earlier graph-based evidence is not used.
