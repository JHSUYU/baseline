# SOLR-36/37 terminal raw trial archive

Archived and verified on 2026-10-07 UTC. This is the shared raw evidence for SOLR-36 and SOLR-37; their case results, final audits, per-trial CSV, code, healthy seeds, and candidate replays remain expanded on node2.

| Item | Value |
| --- | --- |
| Source host and base | `node2:/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-36/independent` |
| Archived relative trees | `campaign/trials/`; `rpc-stage/campaign/trials/` |
| Archive host and path | `node1:/users/ZhenyuLi/archives/solr36-37-20261007/raw-trials.tar.zst` |
| Archive size and SHA-256 | 204,459,613 bytes; `35f0f4a7a4c9f3ada4ee2061b9ccdc8144b62e0b8c34f27085f7c1becf14b620` |
| Raw file count | 12,961 old ZooKeeper trials + 22,037 HTTP actor-V2 trials = **34,998** |
| Source allocated size recovered | 2,303,905,792 + 4,133,044,224 = **6,436,950,016 bytes** |
| Per-file manifest | `node1:/users/ZhenyuLi/archives/solr36-37-20261007/raw-trials-manifest.jsonl`; SHA-256 `3ec170fa7cea8441298d16ad0ac0ce3e099754758f07aac730d35f95c7877f4a` |
| Committed manifest copy | `raw-trials-manifest.jsonl.gz`; decompresses to the same manifest SHA-256 |
| Sidecar metadata | `node1:/users/ZhenyuLi/archives/solr36-37-20261007/metadata/`; 12 source files match `metadata-sha256.json` (SHA-256 `f31b35944c9e31e4d2ef77fa2400a0882ca752aeea1e25ecadd61946796fbd62`) |

The old ZooKeeper state is `budget_complete`, 128 plans, no active trial, SHA-256 `ff52773c48b3c58b829e74a39c38f214d1882c25f6a87f78a50207e04bf200ee`. The HTTP actor-V2 state is `budget_complete`, 172 plans, no active trial, SHA-256 `db72a8c7cbc189ae74c29fa9624dd8beabcebc93adf5075d8e51e779c432fc40`; its stage controller is `complete`. The independent HTTP audits and per-trial CSV remain in the case and in the node1 metadata sidecars. The HTTP raw actor audit counted 127 SOLR-36 and 82 SOLR-37 effective trials with zero physical actor mismatches.

Verification before cleanup:

1. The source manifest hashed every regular file and found zero symlinks. The node1 manifest copy matched its SHA-256.
2. `zstd -t` passed. `raw_archive.py verify` streamed the entire decompressed tar, compared each member's path, size, and SHA-256 with the source manifest, and verified **34,998/34,998** files. The archive's SHA-256 matched the streaming writer's output.
3. All 12 node1 metadata sidecars matched their source SHA-256. Their states and final trial-table SHA were cross-checked. Before deletion, node2 had no process with an open file or working directory in either raw tree, and both nodes had over 10 GiB free.
4. Only the two archived `trials/` directories were removed on node2. After deletion they were absent; both state files and stage status remained terminal. Final observed free space: node1 **13,201,207,296 bytes**, node2 **17,939,365,888 bytes**.

## Restore

First verify the archive SHA-256 and the destination's free space. Restoring expands about 6.44 GB of allocated files; leave at least 10 GiB free after extraction. From the shared workspace host, stream the archive directly to the original base path:

```sh
ssh -i ~/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes ZhenyuLi@node1 \
  'zstd -dc /users/ZhenyuLi/archives/solr36-37-20261007/raw-trials.tar.zst' |
ssh -i ~/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes ZhenyuLi@node2 \
  'tar -C /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-36/independent -xf -'
```

Then regenerate and compare the per-file manifest on node2:

```sh
python3 /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-36/independent/archive/raw_archive.py \
  manifest /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-36/independent \
  /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-36/independent/archive/restored-manifest.jsonl
sha256sum /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-36/independent/archive/restored-manifest.jsonl
```

The regenerated manifest must equal `3ec170fa7cea8441298d16ad0ac0ce3e099754758f07aac730d35f95c7877f4a`. Restoring at the original relative paths makes the absolute trace paths in the two terminal state files valid again.
