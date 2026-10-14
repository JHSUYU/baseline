# Archived custom graph campaign data

This directory preserves results from the earlier custom Mallory occurrence-graph
implementation. It is separate from the source-built GraphChecker campaigns and
their authoritative 102-check table in `data/mallory/native_graphchecker_queue/`.

`readiness102.json` is the original 102-check preparation snapshot;
`quality_reviews.json` records historical case reviews. Their former dispatcher
(`Mallory/dispatch/graphchecker_port/`) has been removed because the native
GraphChecker queue and campaign do not import or execute it. These snapshots do
not certify completion under the current native method.
