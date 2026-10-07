# SOLR-10/39/40 terminal campaign V4 raw offload and restore receipt

On 2026-10-07, the shared, completed 757-trial `campaign-v4` evidence tree was
streamed from node1 to node2 as a sparse-aware tar compressed with zstd. The
source is
`/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-10/actor-v2/evidence/campaign-v4/`.
The node2 archive and its per-file manifest are:

| Node2 artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `/users/ZhenyuLi/baseline-evidence-offload/solr103940-campaign-v4-terminal-757-20261007.tar.zst` | 98,942,226 | `a05114a187cfd8130d9ad44c8c66624a8c2ccc61b1189a9669695bf42590c884` |
| `/users/ZhenyuLi/baseline-evidence-offload/solr103940-campaign-v4-terminal-757-20261007.manifest.json` | see file | `f2386225ccd254c72a972b123c916b9fd1063f19171e0af9ab5831591f2ddfa0` |

The source manifest and a full streamed archive traversal agreed on **all
3,911 regular files and 993 directories**, including the untracked
`state.json`, raw JUnit logs, JaCoCo data, events, receipts, and candidate
scratch. Every file matched by relative path, logical size, and SHA-256. The
files total 1,900,430,794 logical bytes. Zstd integrity passed. The archive
and manifest were then atomically published and set read-only on node2.

Before the offload, the original raw audit was recomputed without writing to
the campaign: 757 trials, 481 strict injections, effective counts
SOLR-10=128, SOLR-39=87, SOLR-40=154, and zero issues. Its saved SHA-256 and
the Git blob are both
`b4bb1a9ea035b96d99bd8355967fe86528934d14e4d4f6c789d90a8f11b4a954`.
The terminal `state.json` SHA-256 is
`d410ad2a64d185c8b042f741178c8bfddfb4225cb1a0d2529af2588dd502dc55`;
it records 757 trials and `inflight=null`. The terminal receipt SHA-256 is
`85afb270992c9b03b090e7e794865e6d9323d1a4a9ea60f732bcd23a8284cacc`.
These three hashes remained unchanged after cleanup. Node1 and node2 each
had at least 10 GiB free before archive transfer and cleanup, and no
same-user process had a cwd, file descriptor, or mapping in the campaign tree.

Immediately before deletion, every file in the 737 ordinary trial
directories was hashed again against the verified archive manifest. Only
those 737 directories and their 3,685 completely untracked files were
removed. They contained 1,378,209,644 logical bytes; node1 free space rose
from 13,513,883,648 to 14,911,762,432 bytes, a gain of 1,397,878,784 bytes.
The remaining 20 trial directories retain 156 files, all independently
rehash-checked after cleanup. Their IDs are 018, 023, 029, 036, 163, 179,
223, 224, 227, 271, 323, 329, 330, 420, 421, 481, 526, 527, 636, and
644. This set includes every trial with a selected or any-actor target
exception, every `scratch_retained` trial, and every trial directory with a
Git-tracked raw file. All 14 adjacent candidate/control/replay trees, healthy
runs, checkpoint, audit, terminal receipt, migration evidence, and source
remain on node1. The SOLR-40 outcome remains a reproduced candidate with
novelty pending, not a confirmed new bug.

## Restore

When node1 has at least 10 GiB free, copy the archive from node2 to node1,
verify the archive SHA-256 above, and restore trial members only. The
`--skip-old-files` option preserves the 20 expanded protected trials. This
selective extraction was smoke-tested for two ordinary trials with an
existing-file sentinel and for a nested candidate scratch tree; the newly
extracted files matched the manifest SHA-256 values.

```sh
scp -3 -i ~/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes node2:/users/ZhenyuLi/baseline-evidence-offload/solr103940-campaign-v4-terminal-757-20261007.tar.zst node1:/tmp/solr103940-campaign-v4-terminal-757-20261007.tar.zst
ssh -i ~/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes node1 'sha256sum /tmp/solr103940-campaign-v4-terminal-757-20261007.tar.zst'
ssh -i ~/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes node1 'tar --zstd --skip-old-files -xf /tmp/solr103940-campaign-v4-terminal-757-20261007.tar.zst -C /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-10/actor-v2/evidence --wildcards "campaign-v4/trial-*/*"'
```

The node2 manifest supplies the expected path, size, and SHA-256 for every
restored file. After restoration, the original read-only audit can be rerun
against the complete node1 trial tree. None of the earlier `work/evidence`
campaign or the separate control and replay experiments was deleted.
