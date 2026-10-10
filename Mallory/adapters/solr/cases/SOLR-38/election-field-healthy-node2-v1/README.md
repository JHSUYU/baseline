# SOLR-38 election and leader-field healthy observation

The unchanged Solr 8.11.4 `CloudHttp2SolrClientTest#testAliasHandling`
starts a three-node `MiniSolrCloudCluster`, creates two collections, sends
updates, and queries aliases. Prior v24 healthy evidence passed 1/1 and
reached `DistributedZkUpdateProcessor.doDefensiveChecks@1021` four times on
named node1 and node3. The v24p client HTTP/2 pilot applied four strict
faults and retained zero postfault target checks. Its client I/O therefore
does not establish a useful fault-to-target path.

This one-trial package measures a different, source-backed path. During
`ShardLeaderElectionContext.runLeaderProcess`, the exact
`SolrZkClient.getChildren` calls at lines 396 and 450 can throw
`KeeperException.ConnectionLossException`. The immediately surrounding
`catch (KeeperException)` handles a non-session exception and may continue
election. Successful election writes `CloudDescriptor.isLeader` through
`setLeader(true)` at line 264. The target method reads the same volatile
field through `CloudDescriptor.isLeader()` at lines 982 and 1013 before its
line-1021 guard. The field trace is enabled only for the selected included
classes; automatic I/O doors are disabled. The site catalog admits only the
two exact election calls as typed doors.

The isolated adapter adds an actor scope to `runLeaderProcess` using that
context's actual `zkController` receiver. It leaves the frozen v38 adapter
unchanged and is compiled into its own SHA-pinned JAR. The pinned Mallory
agent records numeric JVM thread IDs, `CloudDescriptor#isLeader` object IDs,
and field versions. Its
versions have `sampled` confidence and are diagnostic evidence only.
`audit_healthy.py` requires named actor/epoch, an election-region door and
field write on the same JVM thread, the same descriptor object on a later
read, and a read within the target region. It separately checks for an
observed graph path that excludes candidate state edges. A sampled field
version by itself never passes that path gate. A target-retaining fault pilot
and source review remain required before any full campaign.

Run `python3 static_preflight.py` for the offline, no-JVM package check.
Dispatch must write a matching `admission-healthy-node2.json` GO receipt
before `run_node2.sh` can start the JUnit. The runner checks node2, a fresh
output, the Solr lane and source locks, 7,650,410,496 free bytes, 8,388,608
KiB available RAM, and no competing user JVM. At staging time node2 had
7,573,876,736 free bytes, below that runtime floor; no JUnit or fault run
was launched while preparing this package.
