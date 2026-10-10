# HBASE-34: isolated MiniKdc classpath repair

The unchanged `TestGenerateDelegationToken#testOnlyToken` is a real HBase cluster test: `SecureTestCluster` starts MiniKdc, MiniZK, MiniDFS, and `LocalHBaseCluster(1)`. Its token-only RPC exercises DIGEST SASL, which calls `AuthenticationTokenSecretManager.retrievePassword`; line 159 checks `masterKey == null` for every unexpired token. The earlier “no suitable cluster test” classification confused this unconditional check with the earlier, conditional key-miss check at line 139. See the pinned independent source receipt in `../hbase34-37-independent-admission-v1/receipt.json`.

The old run stopped in `MiniKdc.start` before any JUnit case ran. The archived stderr reports `NoSuchFieldError: ERR_00003_INVALID_OID` from `Oid.processStateStart`. The distribution has duplicate Apache Directory API releases: `api-asn1-api-2.1.7.jar` defines an `Oid` class that references `I18n.ERR_00003_INVALID_OID`, while `api-i18n-1.0.0-M20.jar` lacks that field. This is a strong linkage explanation; the old run did not record class-load origins, so the precise loaded pair remains an inference.

`healthy.json` makes one isolated classpath change: it places `api-all-1.0.0-M20.jar` explicitly before the distribution wildcard. This jar contains the same M20 `Oid` and `I18n` classes as the separate M20 jars, matching the other ApacheDS M15/M20 dependencies. It retains the original LocalHBaseCluster JUnit and exact HBASE-34 target, uses one healthy trial only, and disables automatic fault-trial promotion. It does not change the shared HBase distribution or source tree.

Offline admission, with no JVM launch:

```sh
python3 Mallory/adapters/hbase/pilot/hbase34-kdc-classpath-v1/preflight.py
```

The preflight pins the source, compiled target and test classes, runtime artifacts, old failure archive, and the ordering of the M20 API jar. It also reads the class constant pool to verify the incompatible 2.1.7 field reference. Static admission passed locally; node1 has the same pinned API jars, but this package has not been copied to or executed on node1. The case remains `pending_environment_repair`. A future isolated healthy run must first show that MiniKdc and the unchanged JUnit pass, then prove a named exact target check and a relevant, observed pretarget I/O path. No full fuzz campaign or bug claim follows from this package alone.
