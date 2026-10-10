# SOLR-38 election probe on independent node1

This port reuses the SHA-pinned node2 healthy configuration, site catalog,
agent, election adapter, Solr worktree revision, and compiled classes on
node1. Its runner uses a distinct output and node1-local Solr locks. Run
`python3 -B run_healthy.py --preflight-only` without a JVM, then dispatch
may issue a case-local `admission-healthy-node1.json` for exactly one
unchanged MiniSolrCloudCluster JUnit. The runner checks host, receipt pins,
free disk, RAM, user JVMs, and fresh output again under the locks.

Full fault admission requires a named election door, matching descriptor
field write and target read, an observed path without candidate state edges,
and a separate target-retaining fault pilot. A passing healthy JUnit alone
does not satisfy those gates.
