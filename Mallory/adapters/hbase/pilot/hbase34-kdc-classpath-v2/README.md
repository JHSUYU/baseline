# HBASE-34 MiniKdc classpath repair v2

The isolated v1 healthy run reached `MiniKdc.start` and no longer had the
Apache Directory `NoSuchFieldError`. It stopped before JUnit discovery with
`NoClassDefFoundError: org/bouncycastle/jce/provider/BouncyCastleProvider` in
`DefaultDirectoryService.createBootstrapEntries`. The pinned node1 v1 stderr
has SHA-256 `e54c42e3d625d9c0625454f4c9cc760152f2c5cf10e796b06f812b97c74d2f49`.
No target check or fault trial was reached in that run.

`healthy.json` retains the unchanged
`TestGenerateDelegationToken#testOnlyToken`, target site, agent, one-trial
healthy budget, and explicit M20 Apache Directory API. It adds the three
locally available Bouncy Castle **1.82** jars immediately after the M20 jar
and before the distribution wildcards: `bcprov`, `bcutil`, and `bcpkix`
`jdk18on`. These are same-version artifacts and their representative classes
have Java 8 compatible class-file major version 52. The HBase source declares
the `jdk18on` provider and PKIX dependency family; it declares version 1.84,
so this package is an offline classpath repair candidate, not proof that the
complete test will pass with 1.82.

The package changes only this case's JVM classpath and pins. It does not edit
the HBase distribution, source, v1 evidence, checklist, or dispatch results.
Automatic fault-trial promotion remains disabled.

Offline validation:

```sh
python3 Mallory/adapters/hbase/pilot/hbase34-kdc-classpath-v2/preflight.py
python3 -m unittest Mallory/adapters/hbase/pilot/hbase34-kdc-classpath-v2/test_preflight.py
```

On node1, use `preflight.py --node1` to verify the actual v1 failure log and
the staged artifact hashes. The dispatch owner can then run **one** healthy
trial after the node1 HBase lane is free. Full fuzz admission requires MiniKdc
startup, the unchanged JUnit to pass, the named exact target check to execute,
and a relevant observed pretarget I/O path. A target exception or a dependency
repair by itself is not a new bug finding.
