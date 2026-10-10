# SOLR-39 independent node1 healthy observation

This package reuses the byte-identical SHA-pinned SOLR-39 v2 healthy config,
site catalog, source, classes, agent, and runner on node1's separate Solr
worktree. It writes to a new node1-only output and uses node1-local Solr lane
and source locks. `preflight.py` verifies every base package pin and runs the
original source, bytecode, and runtime-artifact checks without a JVM.

After node1 is idle, run `python3 -B run_healthy.py --preflight-only`. Dispatch
must then issue `admission-healthy-node1.json` with `go=true`, case/host/mode,
the config and runner SHA-256 values, and the exact intended output. Run one
healthy JUnit with `python3 -B run_healthy.py --admission-receipt
admission-healthy-node1.json`. A passing JUnit alone does not admit a full
campaign: require exact named target, typed watcher door, and observed
watcher-to-cache-to-target handoff before any fault trial.
