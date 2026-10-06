# HDFS-21 source and workload review

The selected `BPServiceActor.checkNNVersion` guard compares the software
version returned by the NameNode with the DataNode's configured minimum
NameNode version. A lower version throws `IncorrectVersionException`. In the
released HDFS 3.4.3 source, `retrieveNamespaceInfo` obtains the value through
`bpNamenode.versionRequest()` during the first DataNode handshake. It retries
`IOException` and `SocketTimeoutException` from that RPC, then invokes the
selected check on the returned `NamespaceInfo`.

The mapped original JUnit, `TestDFSInputStream#testSkipWithRemoteBlockReader`,
starts a `MiniDFSCluster` with builder defaults, writes a 4 MiB file, and tests
remote-reader skipping. The target can occur during cluster startup; the later
file reads are after the version check and do not exercise this startup guard.
An independent healthy trace is still needed to prove the exact check runs in
this test. Fault selection should therefore use observed startup
`versionRequest` RPC calls and require the same guard after the last injected
exception. An RPC failure that prevents the DataNode from starting is a lost
target, not a selected `IncorrectVersionException`.

This check is a direct compatibility comparison of one RPC response with a
configuration threshold. Source review gives no evidence of a multi-hop
coordination invariant for this site; that limits its interpretation as an
ad hoc coordination candidate even if fault testing reaches it. No fault
trial is claimed by this note.
