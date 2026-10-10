# SOLR-38 election value diagnostic v2

The v1 node1 launch stopped before JUnit because node1's offline Maven cache
does not contain `maven-resources-plugin:2.6`. Its output directory was not
created. This package uses a fresh v2 output and admission receipt; it never
resumes the failed v1 attempt.

`build_adapter.py` checks the hashes of the v1 value-hook Java sources, the
pinned Mallory agent, and the previously built election adapter. During the
node1 GO run it compiles the two hook classes with `javac` against that
adapter's relocated ASM classes and the Mallory agent. It then replaces only
the adapter's Solr hook classes in a deterministic ZIP. Maven and network
dependency resolution are not used. The resulting JAR hash is written to the
build receipt, campaign configuration, runtime artifacts, and JUnit pilot
receipt.

`run_pilot.py` verifies the controller's `JAVA_TOOL_OPTIONS` contains exactly
the pinned Mallory agent, and its generated `agent.properties` names this v2
adapter and event file. The wrapper also sets both direct-runner environment
variables explicitly before launching the unchanged
`CloudHttp2SolrClientTest#testAliasHandling` cluster JUnit. The offline audit
cross-checks the pilot's actual agent and adapter hashes against the campaign
configuration.

On any host, run `python3 -B -m unittest -v test_offline.py`,
`python3 -B build_adapter.py --preflight-only`, and
`python3 -B run_healthy.py --preflight-only` without starting a JVM.
The node1 steward may then create this package's
`admission-healthy-node1.json` with the exact preflight fields, `go: true`,
and `scope: one_healthy_junit_no_fault`, and run
`python3 -B run_healthy.py --admission-receipt admission-healthy-node1.json`.
The runner takes the node1 Solr lane and source locks and requires a fresh
output. It runs one healthy JUnit only. Audit with
`python3 -B audit_healthy.py <healthy-output> --out <audit-file>`.

The old healthy trace has four typed election I/O doors, matching descriptor
field writes and reads, and 12 exact target checks. The field edge is sampled
and remains candidate evidence. This diagnostic does not authorize a full
campaign or a bug claim.
