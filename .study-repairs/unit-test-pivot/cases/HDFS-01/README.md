# HDFS-01: empty located-block response during positional read

**Status: quality complete, no confirmed new bug.** The independent campaign
completed 128/128 fault trials in 2,501.794 seconds of JUnit execution. Every
sequence applied at its requested runtime selectors. In 98 trials, the exact
target check still ran after the final injected fault; no trial reached its
`EOFException` throw. Two ten-fault sequences were executed and retained the
target. Production feedback added 50 covered methods, 186 covered branch-count
IDs, 373 JaCoCo probes, and 385 covered lines beyond the healthy run. The
last eight trials added no new production coverage or stable I/O family.

## Original test and target

Hadoop 3.4.3's unchanged `org.apache.hadoop.hdfs.TestPread#testPreadDFS`
starts a three-DataNode `MiniDFSCluster`, writes a file, and performs two rounds
of positional reads. The test runs from Hadoop's original test JAR with its
JUnit fixture and rules. No Docker cluster or replacement workload is used.

The selected check is `DFSInputStream.fetchBlockAt(long,long,boolean)` at
`DFSInputStream.java:517–518`: after `dfsClient.getLocatedBlocks`, a null or
empty `LocatedBlocks` response raises `EOFException("Could not find target
position …")`. A case-local ASM overlay records the exact conditional check
immediately before its `IFNULL` bytecode and the explicit target throw. It
also records the client-side `DFSClient.getLocatedBlocks` entry and
`Client.getRpcResponse` I/O boundary. The first bounded trials showed those
RPC exceptions exit the JUnit before a later target check, so the scope was
expanded to the original test's observed `BlockReaderRemote.read(byte[],int,int)`
data-transfer I/O. The original test's `DataStreamer for file /preadtest.dat`
RPC response events are also available for periodic exploration because
streaming writes affect the blocks later read by the selected check. The
original production class files are
read from the Hadoop 3.4.3 distribution; the overlay is local to this case.

The current clean healthy run passed in **22.485 s**. It reached the selected check
**18 times**, always with at least one located block, and raised no target
`EOFException`. The trace recorded **220** observed I/O events, including six
main-thread data-transfer reads. The earlier RPC-only healthy seed also passed
in 19.876 s and is retained in `evidence/healthy-rpc-only/`. JaCoCo
collected production HDFS and IPC method, line, branch-count, and probe
feedback. The healthy evidence is in `evidence/healthy/`; the patched bytecode
around the exact condition and throw is in `evidence/target-bytecode.txt`.

## Instrumentation provenance

This case uses independent, case-local **ASM 9.6 offline bytecode hooks** in
`probe/src/PatchHdfs01.java`. It reads the unmodified Hadoop 3.4.3 binary
classes and writes a small classpath overlay for the exact target branch,
`DFSClient.getLocatedBlocks`, `Client.getRpcResponse`, and
`BlockReaderRemote.read`. `probe/src/Hdfs01Probe.java` emits JSONL events and
applies the requested Java I/O exception at the exact runtime identity.
`probe/src/RunJUnitMethod.java` invokes the unchanged upstream test method and
its original JUnit fixture. **JaCoCo 0.8.15** supplies production HDFS/IPC
coverage; the case-local coverage converter records probe, method, line, and
branch-count feedback. The original Hadoop test resource directory is used
only for the upstream test's log configuration.

No GraphChecker prewoven class, runtime JAR, region skeleton, static I/O map,
causal graph, closure, or aggregate is in this runtime path. The selected
target identity came from the research checklist and was verified by the
healthy runtime hook; I/O candidates are chosen from the actual test trace.

## Fault campaign

`probe/campaign.py` reads the observed I/O identities and runs the same
original JUnit in a fresh MiniDFSCluster for each sequence. Faults are
`IOException`, `SocketTimeoutException`, or `EOFException` at exact runtime
selectors: marker, site, client thread, occurrence, and ordinal. Every
mutation adds one fault after the prior injected event. New observed I/O and
new production coverage prioritize sequences; no graph is built or queried.
The coarse I/O scope is the main positional-read client and the test file's
DataStreamer. It prioritizes data-transfer reads that retain the target and
periodically samples streaming RPCs. This graph-free selection is separate
from the bytecode instrumentation described above.
Only sequences with every fault applied in order and a later execution of the
same target check contribute feedback. A lost target is recorded separately.

The initial budget was **64 trials and six faults per sequence**. Trial 62
added two production branch counts, four probes, and four covered lines,
so the same checkpoint continued to **128 trials and ten faults
per sequence**. Each completed trial atomically
updates `evidence/campaign-state.json` and `result.json`; an interrupted
`current` sequence is resumed without redoing completed trial IDs. The node0
campaign ran in tmux session `hdfs01-campaign`. Its command was:

```sh
python3 -u probe/campaign.py --max-trials 128 --max-faults 10
```

The oracle is the exact `TARGET_THROW` event for the selected line 518
`EOFException` after an applied fault. Such an event is a candidate requiring
replay and source review, not an automatic new-bug claim. An injected I/O
exception or JUnit failure alone is not the target oracle.

## Source interpretation

`DFSClient.getLocatedBlocks` is a thin wrapper around the NameNode
`getBlockLocations` RPC. The selected guard compares the returned block-list
emptiness with the requested read offset and the stream's locally cached file
metadata. The original test exercises stale DataNode locations by restarting
DataNodes, but does not concurrently truncate or delete the file during a
read. This site therefore has a direct client/NameNode response-validation
shape in this workload; evidence for a deeper multi-hop control-plane
coordination dependency would require tracing the NameNode state that produced
the response. No target exception observed in this campaign should be
interpreted only within the original test and tested I/O families.
