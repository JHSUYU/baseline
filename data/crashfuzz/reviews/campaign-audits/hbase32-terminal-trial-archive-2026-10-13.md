# HBASE-32 terminal trial archive

The original HBASE-32 campaign had already finished (`budget_or_queue_complete`, 80 fault trials) and had no active worker or JUnit when its raw trial tree was archived on node1. The trial tree was `/users/ZhenyuLi/static-rerun/results/HBASE-32/campaign/HBASE-32/trials`.

The archive at `node1:/users/ZhenyuLi/static-rerun/results/HBASE-32/terminal-trial-archive/trials.tar.zst` contains 898 files totaling 2,509,089,659 uncompressed bytes. Its size is 131,376,045 bytes and its SHA-256 is `fbddba97da59c1e7d6300e2955b69558a48c495dc61fe8e383d7ec686dc07848`. Every regular file was hashed before compression and verified against its decompressed archive member before the raw tree was removed. The per-file manifest SHA-256 is `1d077bf5eeedcd0bdf6e893a7319b84d33f9a1cacb8562db03918b97ebab32af`.

The receipt is `node1:/users/ZhenyuLi/static-rerun/results/HBASE-32/terminal-trial-archive/receipt.json`. It records the original and archive paths, their size and hash evidence, and hashes for `case-summary.json`, `campaign/HBASE-32/state.json`, `campaign/HBASE-32/result.json`, and `campaign-config.json`. Those four files remain at their original paths, so the result table and checkpoint still resolve without extracting the archive.
