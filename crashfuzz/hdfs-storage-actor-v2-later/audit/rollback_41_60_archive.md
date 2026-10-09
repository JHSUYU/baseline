# HDFS-26/37 rollback completed runs 41–60 archive

At 2026-10-07 10:35 UTC, node2's running `rollback-constructor` checkpoint
had more than 60 completed plans. The archive script selected only completed
indices 41–60, checked that none was its in-flight ID, and included every
regular file from those 20 immutable run directories: 220 files totaling
174,017,871 bytes. The archive was built, extracted, and verified file by file
on node2, then copied to node1, restored, and independently verified file by
file there. The source JUnit supervisor continued its own in-flight plan; no
campaign state or plan was changed by archiving.

| Evidence | SHA256 |
| --- | --- |
| `rollback-0041-0060.tar.zst` | `63bd48aac6cfd8b813e81a9bce62bb78f58e445cf0fcec3aaae40b66624a9183` |
| `rollback-0041-0060.manifest.json` | `f01b96dc145cdb1dc4b66898bae467267c2254ab3deabecf4e67fc26f9121005` |
| node2 local 220-file verification receipt | `bd179acbdbb1b03b79055d40a096ae25bca5c6a0eae6ea75740cb1a0dbcf30de` |
| node1 restored 220-file verification receipt | `f1b96c4d732dfe6f7ed4644c747d40b650426d57fa0068b9b59aedca88a2fb3c` |
| node2 `verified-pruned.json` after this batch | `d1435c3fa2b09d7eaefdc487cf76a85eafa221a9492a13dd1b64dd0481526b33` |

The node1 receipt was copied back to node2 before pruning. Only 55 verified
`covered_*.txt` or scratch files in runs with **no** postfault target throw
were removed from node2, totaling 79,590,584 bytes. Every trace, original
JUnit log, JaCoCo file, manifest, and every local run with a target throw
remains. All removed bytes are in the verified archive and restored on node1.
The node2 independent raw checkpoint audit after cleanup passed at 66/66
strict plans, HDFS-26 32 effective, HDFS-37 33 effective, zero issues, zero
novel target throw. The 35 HDFS-37 selected throws all match the signatures
seen in both healthy seeds. No old coarse trials were imported.
The HDFS-43 owner checked overlapping original JUnit trials 97–100 at
17.77/17.99/28.35/27.41 seconds against its 15–29-second same-depth band;
none exceeded 2× during the archive window.
