# ZOOKEEPER-12 FileNotFoundException pilot: operand review

This review is bound to the unmodified three-peer
`CurrentEpochWriteFailureTest#testReadCurrentEpochFromAcceptedEpochTmpFile`,
patched `QuorumPeer.java` SHA-256
`16d7e9723d16a984c65f3a971ea24fd8fb7381311d9db711b2bbc4970daa3270`,
and the six-trial pilot result SHA-256
`40cc484a1b6c11736ba064184d3b335bac6e4a8fc9f4a43182c136979456f06e`.
The offline audit SHA-256 is
`a3b0bd036331c74669db03d360d02c6cc0c23937e995077f132076a7020475b2`.
Per-trial event and result hashes are in
`data/mallory/admissions/ZOOKEEPER-12-fa5f-filenotfound-v1-pilot.json`
(SHA-256 `037ca40b0e73d80227fe7e14a8a9650c732ca13832f004465942aadbfe5aedba`).

`loadDataBase()` reads `currentEpoch` at line 1152, conditionally reads
`currentEpoch.tmp` at line 1170, reads `acceptedEpoch` at line 1180, and
evaluates `acceptedEpoch < currentEpoch` at line 1193. The configured
`readLongFromFile()` door is the `BufferedReader.readLine()` call at line 2190.
The trace records the door ordinal and actor, not the filename or the numeric
epoch operands; the file mapping below follows source call order for each
observed target occurrence.

| Trial | Actor | Door ordinal and source inference | Same-occurrence check | Operand effect from source | JUnit |
| --- | --- | --- | --- | --- | --- |
| r0001 | zk0 epoch 2 | 3, acceptedEpoch | fault seq 672 → check 673 | Local `FileNotFoundException` catch sets `acceptedEpoch = epochOfZxid`; no dynamic numeric value recorded | passed |
| r0002 | zk0 epoch 2 | 2, currentEpoch.tmp | No check after fault seq 655 | No local catch around the tmp read; startup exits before the selected guard | failed |
| r0003 | zk0 epoch 2 | 1, currentEpoch | fault seq 654 → check 656 | Local catch sets `currentEpoch = epochOfZxid`; subsequent tmp/accepted reads and guard remain reachable | passed |
| r0004 | zk0 epoch 1 | 2, acceptedEpoch | fault seq 294 → check 299 | Local catch sets `acceptedEpoch = epochOfZxid`; no dynamic numeric value recorded | passed |
| r0005 | zk0 epoch 1 | 1, currentEpoch | fault seq 291 → check 299 | Local catch sets `currentEpoch = epochOfZxid`; guard remains reachable | passed |

The pilot establishes four exact fault-to-target continuations and zero selected
`IOException` throws. It does not establish the runtime values of either
operand or a new bug. The private 80-trial campaign explores combinations of
these observed doors under the pinned budget; its result requires separate
terminal and source review.
