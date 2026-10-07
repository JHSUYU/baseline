# HDFS-12 completed historical runs on node2

To keep space available for active embedded-cluster campaigns, the two completed **historical** HDFS-12 run trees on node2 were archived on node1. This does not change the completed actor V2 budget or its evidence.

- Node1 archive: `/users/ZhenyuLi/hdfs12-node2-completed-runs.tar.zst`
- SHA-256: `ff22effb3a69c4d8596918688c527a1998de2c8021d3afe79538b28395a88637`
- Compressed size: about 92 MiB; uncompressed tar size: 1,634,068,480 bytes.
- Contents: `independent/long-lived/runs` (80 trial directories, about 612 MiB on node2) and `independent/long-lived/control-plane/runs` (126 trial directories, about 963 MiB). The archive has exactly 206 trial directories.
- Verification **before node2 cleanup**: node1 `zstd -t` passed, and streaming the entire archive through `zstd -dc | tar -df -` against the node2 originals passed with no content or metadata differences. No HDFS-12 process was using these trees.

To restore on node2, run from node0:

```sh
ssh -i ~/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes ZhenyuLi@node1 \
  'cat /users/ZhenyuLi/hdfs12-node2-completed-runs.tar.zst' | zstd -dc | \
  ssh -i ~/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes ZhenyuLi@node2 \
  'tar -C /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HDFS-12 -xf -'
```

The active HDFS-12 actor V2 evidence is on node1 and was not moved. An older independent archive described in `independent-archive-manifest.json` does **not** match the full node2 run trees and was not used to justify this cleanup.
