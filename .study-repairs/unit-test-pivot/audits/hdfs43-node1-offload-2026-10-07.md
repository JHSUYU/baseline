# HDFS-43 node1 evidence offload

HDFS-43 was already terminal before this disk-space operation. No HDFS-43
JUnit or controller process was running on node1. The offload did not change
the case result, trial count, or raw bytes.

- Original trees: `cases/HDFS-43/independent/evidence` (720 MiB) and
  `cases/HDFS-43/independent/equal_phase/evidence` (1.3 GiB).
- Manifest: 2,359 regular files, SHA-256
  `27db409876f2c58a92e271a96bb171827642ef73cfec11f6a07b0fd25d37b672`.
- Archive: `raw-evidence.tar.zst`, 120,729,017 bytes, SHA-256
  `d777de0d3fd4653982c7297d5ebe00c4293e11808807ecc0aaab688e8466c1e4`.
- Identical archive and manifest remain on **node1 and node2** at
  `/users/ZhenyuLi/baseline-evidence-offload/hdfs43-independent-20261007/`.
- Before deleting the node1 expanded trees, `sha256sum -c` passed for all
  2,359 original files. On node2, the copied archive and manifest passed
  SHA-256 checks; a complete temporary extraction passed all 2,359 file
  checks. The temporary extraction was removed after verification.
- Only the two expanded node1 evidence trees were then removed. The node1
  free-space reading rose to 13,742,596,096 bytes. Scripts and result files
  under `independent/` remain in place.

To restore the expanded evidence on node1:

```sh
cd /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HDFS-43
tar -I zstd -xf /users/ZhenyuLi/baseline-evidence-offload/hdfs43-independent-20261007/raw-evidence.tar.zst
sha256sum -c /users/ZhenyuLi/baseline-evidence-offload/hdfs43-independent-20261007/raw-files.sha256
```
