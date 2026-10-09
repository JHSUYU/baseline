# HDFS-39 historical raw trial archive

The **historical, pre-actor-aware** HDFS-39 campaign's 205 `trial-*` directories were moved off node0 to leave disk for the current embedded-cluster campaigns. They are not counted in the separate HDFS-39 actor V2 effective denominator. The campaign scripts, checkpoint, plan files, and audit summaries remain in this directory.

- Archive on node1: `/users/ZhenyuLi/hdfs39-legacy-trials.tar.zst`
- SHA-256: `60a115fd40798ae5cccc42970bbd961aa8323a37fa0a8c18c50828a59326ca4e`
- Size: about 50 MiB compressed, 955,904,000 bytes uncompressed.
- Verification before local cleanup: node1 `zstd -t` passed; streaming the complete remote archive through `zstd -dc | tar -df -` against the original node0 campaign directory passed with no byte or metadata differences; the archive contains exactly 205 trial directories.

To restore on node0, from `independent-coverage-io/campaign` run:

```sh
ssh -i ~/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes ZhenyuLi@node1 \
  'cat /users/ZhenyuLi/hdfs39-legacy-trials.tar.zst' | zstd -dc | tar -xf -
```

The actor-aware V2 campaign is under `hdfs39-rpc-actor-v2/` and was not moved.
