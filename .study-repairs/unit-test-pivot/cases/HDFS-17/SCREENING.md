# HDFS-17 source screening: redundant `StatefulBlockInfo` precondition

**Verdict:** `source_excluded`; this selected check does not expose an
independent ad hoc coordination condition in Hadoop HDFS 3.4.3. The original
cluster JUnit and one identity-matched diagnostic fault trial ran, but an
80-trial campaign would search a condition already entailed by the immediately
dominating local predicate.

The only `new StatefulBlockInfo(...)` in the released `BlockManager.java` is
under `if (isBlockUnderConstruction(storedBlock, ucState, reportedState))`
(lines 3466-3468). The constructor checks `!storedBlock.isComplete()` at
line 2851. The helper returns true for `FINALIZED` only when the stored block
state is `UNDER_CONSTRUCTION` or `UNDER_RECOVERY`; for `RBW` and `RWR`, it
returns `!storedBlock.isComplete()` directly (lines 3668-3680). The
`ucState` passed to the helper is read from that exact `storedBlock` at
line 3438. `BlockInfo.getBlockUCState()` and `isComplete()` show that complete
means precisely `getBlockUCState() == COMPLETE` (lines 373-383). There is no
state-changing call between the helper's true result and the constructor;
`new Block(block)` copies the *reported* block. Full reports run under
`namesystem.writeLock()` in `processReport` (line 2895). The incremental
report path asserts that the same write lock is held (line 4611).

Thus, for every normal entry to this constructor, the predecessor predicate
implies its precondition. An I/O exception can change which reports reach
this point, but cannot make this precondition false on this path unless the
NameNode's block state is mutated outside its locking contract. That would be
a separate invariant violation, not a fault-induced branch of this check.

Runtime confirmation uses the unmodified released test
`TestAddStripedBlocks#testAddUCReplica` from the Hadoop 3.4.3 test JAR. The
original one-NameNode, nine-DataNode JUnit passed in 38.927 seconds. The
case-local ASM/JaCoCo healthy run passed in 39.165 seconds, recorded nine
checks for stored block `-9223372036854775792` with true condition, and
observed 18 block-report RPCs from nine distinct DataNode UUIDs. A diagnostic
`IOException` matched `BPServiceActor.blockReport#full` on logical
`hdfs/blockpool/0/dn/0`, hit ordinal 1. It was applied once; the original
JUnit passed in 43.757 seconds and the same stored block reached the check
nine times after the fault, all true. No selected exception appeared. This
diagnostic is not presented as full fuzz coverage.

The release evidence is
`/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3/share/hadoop/hdfs/sources/hadoop-hdfs-3.4.3-sources.jar`
(`BlockManager.java`, `BlockInfo.java`) and the corresponding released
`hadoop-hdfs-3.4.3-tests.jar`. Runtime evidence is in
`independent/healthy-instrumented-02/` and `independent/smoke-dn0-01/`.
The earlier pool-only diagnostic was superseded when the probe was refined
to retain per-DataNode identity.

For candidate screening, this case illustrates a rule: when a selected guard
is entailed by a dominating predicate on the same object under one lock,
classify it as a local defensive invariant even if the surrounding path
processes remote data. Trace the exact object alias and branch semantics
before assigning a fuzz budget.
