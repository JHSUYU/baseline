# HBASE-28 source review

The selected check is `HRegionServer.putUpWebUI` at line 2487 in unchanged
HBase 2.6.6 commit `d5f63f523c065f963992ea4e74db268d17816631`.
It reads `hbase.regionserver.info.bindAddress` (or the master equivalent),
resolves that configured string with `InetAddress.getByName`, and rejects an
address that does not belong to the current host. This is a local startup
configuration validation. The selected `IOException` is expected for an
invalid bind address and has no dependence on a remote node's state or a
multi-hop coordination decision.

The proposed original JUnit
`TestInfoServers#testInfoServersRedirect` starts a MiniHBaseCluster in its
`@BeforeAll`, with both info ports set to zero (automatic allocation). It
uses the default local/any bind addresses, then checks HTTP status-page
redirects. The source path through construction evaluates the local-address
condition, but the test does not drive an invalid bind address. Injecting a
DNS `UnknownHostException` would exit at `getByName`, before the selected
`if (!Addressing.isLocalAddress(...))` decision; ZooKeeper, RPC, and file I/O
exceptions do not change the configured address or local interface list.

This site is a static-screening false positive for ad hoc coordination. A
fault-injection campaign on the proposed JUnit would exercise startup errors
or HTTP behavior without a causal path to the selected rejection condition.
It is source-excluded with zero fault trials and no runtime bug claim. The
original test and production source were read; the JUnit was not run for this
case.
