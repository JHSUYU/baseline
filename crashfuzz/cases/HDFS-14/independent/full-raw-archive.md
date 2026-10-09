# HDFS-14 full raw trial archive

The completed HDFS-14 campaign's `runs/` directory was copied to node1 before
freeing node0 scratch space. The archive contains every one of the 1,270 raw
files, including JUnit logs, JaCoCo output, traces, plans and manifests for
the 128 completed trials. This is separate from the smaller local
`compact-evidence.tar.gz`.

- Host/path: `ZhenyuLi@node1:/users/ZhenyuLi/hdfs14-full-raw.tar.zst`
- Archive SHA-256: `557711e9f42850700df4d839ba435a01d2c242d6c5586ff616289fd762a5d0dd`
- Compressed size: approximately 57 MiB; uncompressed tar stream: 1,001,697,280 bytes.
- Verification: `zstd -t` passed on node1. Streaming the decoded archive back
  to node0 and running `tar -C independent -df -` against the original tree
  returned 0 with no differences before the node0 copy was removed.

To restore the original relative paths under this directory, run:

```sh
ssh -i /users/ZhenyuLi/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes \
  ZhenyuLi@node1 'zstd -dc /users/ZhenyuLi/hdfs14-full-raw.tar.zst' |
  tar -C /users/ZhenyuLi/baseline/crashfuzz/cases/HDFS-14/independent -xf -
```

The completed result, compact evidence, and independent audit stay in the
repository checkout. No campaign is running from this archived case.
