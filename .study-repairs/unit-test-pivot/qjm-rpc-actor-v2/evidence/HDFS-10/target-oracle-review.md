# HDFS-10 target exception review (2026-10-07 UTC)

The actor-aware V2 campaign uses unchanged
`TestQuorumJournalManager#testSingleWriter` on three embedded JournalNodes.
The six initial post-fault `Journal.checkWriteRequest` IOException events were
incorrectly hidden by an oracle condition requiring nonzero JUnit exit. They
are now candidate **observations** even though all six original JUnits passed.
The correction changed only derived labels, not the 41 trial plans, raw traces,
JaCoCo data, elapsed times, or 27 effective-trial count at the pause boundary.
The before/after derived-field and checkpoint hashes are in
`target-oracle-v2-migration.json`; the pre-migration rows and two fresh replay
fixtures are in `target-oracle-v2-raw.tar.gz` (SHA-256
`a48f63faa67594432e4c5a70f23d77ea31780ea1cf50a8d6e707463894e7e3eb`).

| Original trial | Final physical actor | Second fault | Target throw | JUnit |
| --- | --- | --- | --- | --- |
| 0004 | journalnode-2 | `PersistentLongFile.set` IOException | 1 | pass |
| 0009 | journalnode-1 | same IOException | 1 | pass |
| 0010 | journalnode-0 | same IOException | 1 | pass |
| 0015 | journalnode-1 | `PersistentLongFile.set` FileNotFoundException | 1 | pass |
| 0016 | journalnode-0 | same FileNotFoundException | 1 | pass |
| 0023 | journalnode-2 | same FileNotFoundException | 1 | pass |

Each plan also starts with an actor-bound `Client.getRpcResponse` IOException.
The final file fault is matched and applied on the listed JournalNode; raw
trace records `epochsEqual=false` at the exact target after that fault and a
same-actor IOException. A later target event on the same actor records
`epochsEqual=true`.

Two representative plans were replayed from new test fixtures without
entering the fuzz effective denominator. The original plans and hashes are
preserved in the archive. Replay 0004 (IOException) had 2/2 matched/applied,
same `journalnode-2/test-journal` target throw, JUnit exit 0, 10.954 s.
Replay 0015 (FileNotFoundException) had 2/2 matched/applied, same
`journalnode-1/test-journal` target throw, JUnit exit 0, 10.658 s. Both
replays have raw trace, plan, JaCoCo, coverage and strict receipt in the archive.

Hadoop 3.4.3 `Journal.java` provides the direct source explanation:
`startLogSegment` writes `lastWriterEpoch` through the injected
`PersistentLongFile.set` at line 611; `journal` calls `checkWriteRequest` at
line 397; lines 517–520 throw IOException when the request epoch differs from
the persisted writer epoch. The injected write failure leaves the old epoch,
so the target exception is the expected guard response to that fault. The
unchanged JUnit still succeeds with its three-JournalNode quorum. This
equivalence family is source-excluded as a new coordination bug, while its
target exceptions remain recorded as candidate observations for audit.
