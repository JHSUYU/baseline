# Archived prior diagnostic scratch

`solr06-after-v4-2026-10-05.tar.zst` preserves the older CrashFuzz
`/tmp/solr06-after-v4` tree, including its run traces and logs. It is legacy
diagnostic evidence and is not an input to the independent SOLR-06 campaign.

Before removing the original `/tmp` copy on 2026-10-06, the archive's 4,401
entries (including its root directory) were compared against the original
files with `zstd -dc ... | tar -C /tmp -df -`; the comparison exited 0.
SHA-256: `8407ce664164882c113be8448b39ebfe36bb5be2fa0103462a7b9c6da9f8b843`.

Restore with `zstd -dc solr06-after-v4-2026-10-05.tar.zst | tar -C /tmp -xf -`.
