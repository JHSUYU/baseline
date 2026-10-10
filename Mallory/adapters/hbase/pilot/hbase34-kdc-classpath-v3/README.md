# HBASE-34: isolated HTTP test helper for the secure cluster JUnit

The sealed v2 healthy trial started MiniKdc and MiniZooKeeper, then stopped
before JUnit discovery at `HBaseKerberosUtils.setSSLConfiguration` because
`org.apache.hadoop.hbase.http.ssl.KeyStoreTestUtil` was absent. The exact
stderr is pinned in `manifest.json`; the raw node1 stderr SHA-256 is
`9fa2fa5d379497243b09bc9fed8aabbd0569eb41699ba89ecb323a2be96ec994`.
No target check or fault trial occurred in v2.

The HBase server test POM declares an `hbase-http` **test JAR** dependency,
but the installed distribution has no such test JAR. `build_helper.py`
compiles only the missing `KeyStoreTestUtil.java` from the pinned HBase 2.6.6
source with Java 8 and produces a deterministic, one-class JAR. The source,
compiled class, and JAR hashes are pinned. This does not modify HBase source
or its installed distribution.

The unchanged `SecureTestCluster` calls `KeyStoreTestUtil.getClasspathDir`
with its own class as the resource anchor. That helper derives a writable
directory from the class resource URL. The installed `hbase-server` test JAR
does not provide a filesystem directory URL. `run_case.py` therefore copies
the **byte-identical** `SecureTestCluster.class` from the pinned test JAR and
the compiled helper class into the current Mallory trial directory before
executing the original Java command. The directory precedes the distribution
wildcard on the classpath; SSL files stay within that trial's output. The
wrapper preserves `JAVA_TOOL_OPTIONS` so Mallory instrumentation still runs.

Only the case command, classpath, and artifact pins change from v2. The
unchanged `TestGenerateDelegationToken#testOnlyToken`, exact target, one-trial
healthy budget, M20 Directory API, BC 1.82 jars, and disabled automatic fault
promotion remain pinned. No JUnit or fault run is part of this package.

```sh
python3 Mallory/adapters/hbase/pilot/hbase34-kdc-classpath-v3/preflight.py
python3 -m unittest Mallory/adapters/hbase/pilot/hbase34-kdc-classpath-v3/test_preflight.py
```

After node1 staging, run `preflight.py --node1`. Dispatch may then run one
healthy trial when the node1 lane is free. A full campaign needs a passing
JUnit, the named exact target check, and a relevant observed pretarget I/O
path. Another environment failure remains a pending repair, not a completed
check or new bug.
