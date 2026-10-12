# Solr runtime actor identity calibration (2026-10-12)

This is an isolated instrumentation calibration for SOLR-36, not a completed
original102 campaign result or a bug report. The unchanged
`org.apache.solr.cloud.api.collections.ShardSplitTest#test` ran against the
original Solr 8.11.4 embedded cluster on node2. Its Soot selection was
`results/SOLR-36/caller-expanded/soot-selection.json` (SHA-256
`36fa7ee9bcdc4395dc4f16e4aa82b2fd6918eeb9c79380d15bc73775c854d640`).
The patched agent JAR was staged independently at
`/users/ZhenyuLi/solr-actor-pilot/runtime-agent/target/crashfuzz-runtime-agent-0.1.0.jar`
(SHA-256 `a7ac16382be53bbfa565728cca45425b562fd4f938c1dd76d226f69467cf6775`).
The original102 workers and their checkpoints were not modified by these runs.

| Run | JUnit exit | Time (s) | I/O events | Identity gaps | Target reaches | Matched/applied faults | Trace SHA-256 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Healthy | 0 | 101.559 | 7,696 | 5 | 82 | 0/0 | `a6d39c44416262a1955ef71ec49cf6c232307b437c010007c1a0d78ad95572b5` |
| First replay | 1 | 22.124 | 22 | 5 | 0 | 1/1 | `4794d6cd2bdabc157f30adfab00c0a967214933526c2a5b7527ceed19c1f65b4` |
| Replay after target | 0 | 106.480 | 7,650 | 5 | 90 | 1/1 | `fbcccb91b40eef2a6f5c7a65195dffd9710537f3677698af4b51deec3322cbc9` |

The first replay injected `IOException` before `JavabinLoader.load` closed an
input stream on `solr:http:replica:core_node3`. It matched a Jetty thread with
a different numeric name from the healthy run, but it removed the target and
therefore is not a valid target trial. The second replay injected at
`SolrCmdDistributor.doRequest` on `solr:update:replica:core_node11`. Its
`FAULT_MATCHED` event was sequence 10,560; the target was reached 32 times
before and 58 times after that event. The JUnit passed, showing that a fault
can be matched across fresh clusters while retaining the target. Neither
replay produced a target exception candidate.

The agent derives a stable replica or core identity from Solr's request
context or executor MDC, and marks volatile threads without either identity
as gaps. It uses a per-logical-actor occurrence ordinal for replay. The
healthy trace had 7,696 observed I/O events, of which five startup events
lacked a stable replica/core identity. The traces, manifests, JUnit logs, and
fault plans remain under `/users/ZhenyuLi/solr-actor-pilot/` on node2.
