# Archived trial restoration

Some completed Mallory cases keep their trial evidence in the checksum-sealed
`evidence_archives/campaign/<CASE>.tar.gz` archive rather than as a second loose
copy in `cases/<CASE>/trials`. The case `result.json` remains in place. The
archive and manifest SHA-256 values are recorded in that result and in each
maintenance receipt.

To verify an archive and its relationship to the case result:

```sh
python3 Mallory/ops/restore_archived_trials.py --data-root data/mallory --case HDFS-43
```

To restore its raw trials before a tool needs them:

```sh
python3 Mallory/ops/restore_archived_trials.py --data-root data/mallory --case HDFS-43 --restore
```

The command validates the archive SHA-256, manifest membership, archived
result, and case receipt, then checks every restored trial file against the
archive. It refuses to overwrite an existing `trials` directory. Run the
verification command again after restoration if desired. For the 16 node0
cases reclaimed on 2026-10-10, exact case IDs, source and archive paths, trial
counts, tree and archive hashes, pre/post disk space, and per-case restore
commands are in `node0-terminal-trials-reclaim-20261010.json`.
