# SOLR-07 legacy evidence archive

The prior SOLR-07 generated directories were archived before cleanup to
preserve their trial traces and instrumentation provenance. This is historical
evidence, not part of the current graph-free campaign or its trial count.

- Archive: `SOLR-07-legacy.tar.zst`
- SHA-256: `13ea22e332a0142ea69ac8e42dab610b31508c21a6f21000750fb2aa2c2ae63e`
- Original extracted size: approximately 4.4 GiB
- Verification: `zstd -t` and `tar -I zstd -tf` completed successfully.
- Case result retained in `cases/SOLR-07/result.json`.

Restore with `tar -I zstd -xf SOLR-07-legacy.tar.zst -C cases` from this
directory if source-level review of an old trial is needed.
