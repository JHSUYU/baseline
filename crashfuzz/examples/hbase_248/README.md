# HBase 2.4.8 cluster adapter

This adapter runs two HBase masters and three RegionServers as independently
killable Java 8 containers. A separate NameNode, DataNode, and ZooKeeper
container supply the storage and coordination services. The target is the
`HMaster.checkTableModifiable` guard for `TableNotDisabledException`, which
the create/disable/truncate workload should reach on its healthy arm. The
target branch ID was checked against the compiled HBase 2.4.8 bytecode.

The checked-out HBase source is the `rel/2.4.8` worktree at
`/users/ZhenyuLi/hbase-2.4.8`. Build its distribution on Java 8 with:

```bash
mvn -DskipTests -Dcheckstyle.skip -Drat.skip \
  -pl hbase-assembly -am package assembly:single
tar -xzf hbase-assembly/target/hbase-2.4.8-bin.tar.gz \
  -C /users/ZhenyuLi/.baseline-deps
```

Put an unpacked Hadoop 2.10.0 binary distribution at
`/users/ZhenyuLi/.baseline-deps/hadoop-2.10.0`. The setup accepts overrides
through `ADHOCFUZZ_HBASE_DIST` and `ADHOCFUZZ_HADOOP_DIST`. It uses the local
`causynth-openjdk8-build:ubuntu18` image by default; set
`ADHOCFUZZ_JAVA8_IMAGE` to a Java 8 image with Bash to use another image.
Build the probe in `baseline/crashfuzz/agent`, then run the campaign from
`baseline/crashfuzz`:

```bash
PYTHONPATH=src python3 -m adhoc_crashfuzz.cli run \
  --config examples/hbase_248/campaign.json
```

The initial configuration bounds the campaign to one seed and one injected
run. Its probe scope is deliberately narrow. The HBase 2.4.8 adapter pairs
Netty RPC requests and responses by client socket endpoint and call ID, and
tracks the CallRunner and procedure-worker handoffs by task identity. The
generic graph builder is unchanged. On the healthy truncate workload, the
target closure contained 21 concrete method occurrences and 37 edges,
including one cross-process message and two cross-thread handoff edges.
Two request receives from the uninstrumented readiness client remain explicit
unpaired gaps. This is a concrete may-influence graph, not an exact data-flow
proof.

`ADHOCFUZZ_ZK_SESSION_TIMEOUT_MS` optionally overrides the default 90-second
ZooKeeper session timeout for faster fault-recovery smoke tests. Record the
chosen timeout with experiment results, since it changes recovery timing.
The first two-run smoke test injected a Master crash at the selected point,
but did not reach the target fatal check; it is not a bug finding.

The setup resets all containers and state for each trial. It leaves the last
trial's containers running so their logs can be inspected; remove them with
`sudo -n docker rm -f` followed by the eight `adhocfuzz-hbase-*` names. The
Docker network is `adhocfuzz-hbase`.
