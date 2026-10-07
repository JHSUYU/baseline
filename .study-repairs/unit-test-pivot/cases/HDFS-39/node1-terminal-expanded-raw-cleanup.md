# HDFS-39 node1 terminal trial raw cleanup and restore receipt

At 2026-10-07 13:52 UTC, the completed HDFS-39 actor V2 campaign on node1 had
checkpoint SHA-256 `bc93ac1b343e98fb9d8a5bd4b49e7f287531be1875dffb104f0548ab3975397c`,
status `budget_complete_80`, and `current=null`. No HDFS-39 process was running;
a `/proc` scan found no process with a cwd, file descriptor, or mapping under
an expanded trial directory. The two campaign lock files were acquired
nonblocking for the final verification and removal.

The [committed terminal archive](../../hdfs39-rpc-actor-v2/evidence/hdfs39-v2-terminal-raw.tar.zst)
has SHA-256 `d0f67f187af3421c9d89cbf99ed89656682606b455628e369e688f20da4f9321`.
The Git blob and working archive matched this digest. A full decompression and
tar stream check found 1,227 regular files totaling 922,058,939 bytes, with
no links or special files. Within it, 173 `trial-####-attempt-01` directories
contain 1,038 files totaling 904,352,448 bytes. Every corresponding expanded
node1 file matched its archive member by relative path, size, and SHA-256;
there were no extra or missing trial files. The exact comparison was repeated
under the campaign locks immediately before removal.

Only those 173 expanded trial directories were removed from
`/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/hdfs39-rpc-actor-v2/evidence/`.
Node1 free space rose from 12,835,880,960 to 13,744,902,144 bytes during
removal, a gain of 909,021,184 bytes. The checkpoint SHA remained unchanged.
Both healthy run directories, `campaign-v2/` with its plans and ledgers, the
source image, and the separate `/users/ZhenyuLi/hdfs39-legacy-trials.tar.zst`
were retained. No other case was changed. A later check found zero expanded
trial directories and 13,734,440,960 bytes free; other node1 work explains
the small intervening change in free space.

To restore the expanded trial files, copy the committed archive to node1,
verify its SHA-256 there, then extract only trial members into the evidence
directory. The selective extraction command was tested against trial 0001:
all six restored files matched their archive SHA-256 values.

```sh
scp -i ~/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes .study-repairs/unit-test-pivot/hdfs39-rpc-actor-v2/evidence/hdfs39-v2-terminal-raw.tar.zst node1:/tmp/hdfs39-v2-terminal-raw.tar.zst
ssh -i ~/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes node1 'sha256sum /tmp/hdfs39-v2-terminal-raw.tar.zst'
ssh -i ~/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes node1 'tar --zstd -xf /tmp/hdfs39-v2-terminal-raw.tar.zst -C /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/hdfs39-rpc-actor-v2/evidence --wildcards "./trial-*-attempt-01/*"'
```

The expected archive SHA-256 is the digest above. The [terminal raw audit](../../hdfs39-rpc-actor-v2/evidence/terminal-raw-audit.json),
[archive receipt](../../hdfs39-rpc-actor-v2/evidence/terminal-evidence-receipt.json),
and [terminal review](../../audits/hdfs39-v2-terminal-review-2026-10-07.md)
remain the authoritative classification. The 205 older trials are a separate
legacy campaign and are not part of this cleanup.
