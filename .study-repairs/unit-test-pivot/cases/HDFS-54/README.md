# HDFS-54: striped checksum completion after a stale data-transfer key

This is an **added ad hoc coordination check** in Hadoop 3.4.3 and a
calibration of the **already known HDFS-17897**. It is not a new bug claim.
HDFS-11 is the upstream DataNode key-map guard. HDFS-54 is the distinct
client-side aggregate check whose false outcome fails the original operation.

**Current checklist status: `running_original_junit_supplement`.** The
unchanged released `TestFileChecksum#testStripedAndReplicatedFileChecksum2[0]`
has completed one healthy run (17.72 s) and one strictly matched I/O-fault
trial (17.57 s): **1/80 effective**, with 31 queued plans. The original test
reaches the exact line-629 target after the fault; production JaCoCo coverage
gains four probes over its healthy seed. The original-JUnit runtime
count is **35.29 s** so far. Its full budget has not been completed. See
[`original-junit/README.md`](original-junit/README.md) and the node2
checkpoint for the per-trial evidence.

The separate XOR-2-1 workload below already reproduced the **known**
HDFS-17897 mechanism. Its six mutants and 213.541 s are retained as an
adapted control, excluded from the original-JUnit 1/80 count. The bug mark
`known_HDFS-17897_reproduced` refers to that adapted differential.

## Selected check and source review

The selected condition is in
`hadoop-hdfs-client/src/main/java/org/apache/hadoop/hdfs/FileChecksumHelper.java`,
`StripedFileNonStripedChecksumComputer#checksumBlocks`, line **629**:

```java
if (!checksumBlockGroup(blockGroup)) {
  throw new PathIOException(getSrc(), "Fail to get block checksum for " + locatedBlock);
}
```

`checksumBlockGroup` tries each DN in the striped group (lines 653-675). It
retries `InvalidBlockTokenException` via `if (bgIdx > getLastRetriedIndex())`
at line 659. The released code has no corresponding
`InvalidEncryptionKeyException` catch, so the exception enters the generic
`IOException` handler at line 669 and leaves `done=false` for every DN.
The replicated-file sibling has a key-specific catch and clears the DFS
client's cached key at lines 536-545. This source contrast defines the exact
bug mechanism; a thrown exception alone does not establish the downstream
failure.

The check aggregates the outcomes of multiple remote DNs for one striped
block group. Its inputs depend on the NameNode-issued key, the client's cached
key ID, and the DNs' current block-key maps. The runtime probe records the
line-629 boolean, the line-669 exception type, and the HDFS-11
`BlockTokenSecretManager#retrieveDataEncryptionKey` null-key guard. It joins
that guard to the JUnit's three DNs via each manager object's identity hash,
and verifies the key ID equals the client's cached key ID.

## Adapted known-bug control and differential oracle

The workload is a case-local adaptation of the released 3.4.3 original JUnit
`TestEncryptedTransfer#testFileChecksumWithInvalidEncryptionKey` (source lines
325-372). It retains `MiniDFSCluster`, encrypted data transfer, NameNode key
rotation, and the wait until the old key is absent on the DNs. The change is
one XOR-2-1 erasure-coded file on **1 NameNode + 3 DataNodes**, which executes
the striped checksum branch. The healthy checksum is first recorded. The
post-expiry checksum and a same-client retry are the original operation
oracles. The fixed comparison overlays only a source-level
`InvalidEncryptionKeyException` clear-and-retry branch from upstream
HDFS-17897 fix PR #8364. The same workload must then return the healthy
checksum, and the retry branch must be observed.

In the checkpointed seed, the cached key ID was **1183040781**. The probe
joined three `BlockTokenSecretManager` object identities to the original
DataNode roles: `861318333 → 127.0.0.1:40065`, `4657333 →
127.0.0.1:34725`, and `717730741 → 127.0.0.1:46211`. The first healthy
checksum reached HDFS-54 with `completed=true`. After key expiry, all three
DN managers returned a null value from `allKeys.get(1183040781)` on each of
two checksum attempts, giving six real `InvalidEncryptionKeyException` throws
and six line-669 generic catches. HDFS-54 evaluated `completed=false` twice;
both operations failed with `PathIOException`. The fixed run still encountered
the null-key guard once, then logged the key-cache clear/retry branch and
returned the original healthy checksum. These are run-specific addresses and
object identities, preserved in the raw evidence.

`PatchHdfs11.java` and `PatchStripedCheck.java` use case-local ASM to trace
the exact released-class branches. `Hdfs11Probe.java` records the selected
SASL I/O points and can inject a single planned `IOException` at an observed
post-expiry point. JaCoCo gives code coverage feedback. The second occurrence
in each observed SASL I/O family is prioritized by the first occurrence's
target retention and method/branch coverage gain. `campaign.py` writes
an atomic checkpoint and trial ledger after each run; rerunning it resumes
only missing trials. Fault mutations are generated from the seed's observed
post-expiry SASL I/O sites and marked separately from the real key-expiry
calibration. Trials where the selected check disappears are inconclusive.

## Adapted control run and evidence

```sh
python3 campaign.py --max-mutants 6
```

The completed campaign used 8 runs (one original seed, one fix control, six
single-exception I/O mutants), totaling **213.541 s** of JUnit runtime. All six
mutants matched their planned post-expiry SASL point, retained the exact
HDFS-54 check after the injected fault, and ended in the same known failure.
The fix control completed the checksum. The largest method coverage gain over
the seed was **33 methods**. These mutants test fault-point selection; the
seed and fix differential establish the known bug. No new bug is claimed.

| Trial | Runtime | Applied I/O fault | HDFS-54 false check | Result |
| --- | ---: | ---: | ---: | --- |
| Original seed | 24.732 s | 0 | 2 | Known bug reproduced |
| Fix comparison | 24.834 s | 0 | 0 | Checksum recovered |
| Six I/O mutants | 25.826-28.401 s each | 1 each | 2 each | Target-retaining known failure |

The full per-trial table is in `trial-ledger.csv`; `campaign-state.json`
records time, target outcome, DN identities, exception counts, coverage gains,
and classification. `evidence.tar.gz` contains raw JUnit logs, JSONL runtime
traces, JaCoCo data, the initial instrumented smoke, and the exact I/O plans;
the SHA-256 is in `result.json`. The same files remain in `campaign-runs/`,
`runs/`, and `plans/` in this workspace for checkpoint recovery. The earlier
isolated external control under
`known-bug-controls/HDFS-17897/` is source provenance, not counted as an
HDFS-54 checklist trial.

Upstream references: [HDFS-17897](https://issues.apache.org/jira/browse/HDFS-17897),
[fix PR #8364](https://github.com/apache/hadoop/pull/8364/files).
