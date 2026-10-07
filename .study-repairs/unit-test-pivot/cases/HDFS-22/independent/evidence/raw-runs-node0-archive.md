# HDFS-22 completed raw runs archive

The 83 completed `independent/evidence/runs` directories on node0 were archived after HDFS-22 reached `quality_complete`. The archive is retained locally as `raw-runs-node0.tar.zst` outside Git and on node1 at `/users/ZhenyuLi/hdfs22-node0-completed-runs.tar.zst`.

- SHA-256: `5450223e82dc965f7d86f27a7b2edbbfdef2c33a9cfbb2ba5118d408d79f1563`
- Compressed size: 36 MiB (approximately)
- Verification: node1 `zstd -t` succeeded; the full decompressed tar stream passed `tar -df -` against all original node0 files with no differences.
- The separate `campaign-state.json`, healthy evidence, result, and audit remain on node0.

Restore the raw directories from the case directory:

```sh
zstd -dc independent/evidence/raw-runs-node0.tar.zst | tar -xf -
```
