# HDFS26/37 rollback V2: first 40 completed trial archive

At the node2 complete-trial boundary, `campaign-state.json` listed 40 completed
distinct plans and a separate in-flight plan. The first 40 completed `runs/`
directories were archived. The campaign process and in-flight run were not
changed.

| Evidence | Value |
| --- | --- |
| Original files | 440 regular files, 345,905,024 bytes |
| Archive | `rollback-0001-0040.tar.zst`, 19,846,199 bytes |
| Archive SHA256 | `331f7a1090a9a77f3d9c968c5c1f465451f31d4fd85694879907d51f923d8c66` |
| Manifest SHA256 | `cea1b577a95e81a36f7aef5d1dee192d1d9d484556115ce5b9aa157e0b701377` |
| Node1 mirror receipt SHA256 | `6132e171ec04d2efa34a103982e17cf022e073548746ee003dbf34c0e0633a10` |
| Pruned index SHA256 | `0eebea883370c0351e0e2c0c92be7d7408fd4bfc8b4c8a6e89b44e781c4e8670` |

The manifest records each file's path, size, and SHA256. Node2 extracted and
checked the complete archive before publication. Node1 independently checked
the archive SHA, extracted all 440 files, checked each SHA again, and retained
the expanded run mirror. Only after that receipt returned to node2 did node2
remove 100 archived `covered_*.txt` and scratch files, totaling 144,691,830
bytes, from 20 runs with no postfault target throw. The other 20 runs contain
target throws and retain all local files. Node2 retains every raw trace,
JaCoCo file, original JUnit output, plan, and manifest.

The post-prune independent raw audit passed at 41 completed plans: 41/41 exact
fault sequences, HDFS26 20 effective and HDFS37 20 effective, all 41 original
JUnit methods exit 0. HDFS37's 22 postfault target throws matched both healthy
seeds' expected guard signature; neither case had a novel target signature.
The 41st run was not in this archive and remained intact.

The archive, per-file manifest, mirror receipt, prune index, and post-prune
audit are in `evidence/rollback-constructor/archives/` in both isolated images
`/users/ZhenyuLi/hdfs-storage-v2-later-a4f3ec05f0b5` on node1 and node2.
Archive batches after the first 40 use `archive_completed.py prepare --start
41 --count N`, so no pruned run is rearchived or repeated.
