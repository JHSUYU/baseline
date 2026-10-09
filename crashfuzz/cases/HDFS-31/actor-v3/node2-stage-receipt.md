# HDFS-31 V3 node2 offline stage

At 2026-10-07 12:11 UTC the isolated image was copied to
`/users/ZhenyuLi/hdfs31-actor-v3-20261007/` on node2. The original Hadoop
HDFS test resource tree was copied into its `test-resources/` subdirectory.
No HDFS-31 JUnit or cluster JVM was started.

For each tree, the digest below is SHA-256 over sorted pairs of relative path
bytes and the SHA-256 digest of each file. The local source and node2 copy
matched, and checksum-mode dry-run `rsync -nrc` reported no changed files.

| Tree | Files | Local and node2 digest |
| --- | ---: | --- |
| V3 image, excluding `test-resources/`, this receipt, and Python cache | 33 | `f67003dfcdc5a709ee9d33215f4e74b850e5e27ea7dee8b79b8369310bb0124d` |
| Original HDFS test resources | 63 | `63771954e53cf225e15aac7dcd1695e2da698dca1a6d5d588799d0b21a85c56d` |

The already verified runtime overlay digest is
`24435f63c124d259c328d441361f364b0dcd89e6259382f1110b2f2ab39d41f5`.
Two original healthy JUnit runs and their actor/target audit are still required
before any HDFS-31 fault trial.
