# HBASE-34: final master-key null check in token password lookup

## Exact target and healthy original test

The selected HBase `rel/2.6.6` check is `AuthenticationTokenSecretManager.retrievePassword` line 159, `if (masterKey == null)`, with `InvalidToken("Unknown master key for token...")` at line 160. The unchanged original `TestGenerateDelegationToken#testOnlyToken` starts a Kerberos-enabled local HBase cluster and succeeds in the counted healthy run. Its token password lookup has key ID 1 present and normally returns; JaCoCo covers the final null condition at line 159 and not its throw at line 160. The test's expected `AccessDeniedException` comes from asking for another token while already using token authentication, outside this target method.

## Observed I/O, identity, and feedback

The case-local ByteBuddy probe observed two inbound SASL network frames on the same Netty channel during the sole original `testToken` invocation: an empty frame followed by a credential frame. The target lookup occurs synchronously inside processing of the credential frame. The agent records each frame's hit index, channel, byte count, chosen exception, match/application, target entry and exit, key ID, and original JUnit outcome. It also marks the enclosing `testToken` call and the one `whoAmI` service dispatch. An injected frame failure closes its channel, and the original pending client call can retry on a replacement channel. A valid trial requires ordered exact fault application, all faults inside that one call, one `whoAmI` service dispatch, and a target lookup after the final fault. It requires JaCoCo line 159 and a normal return or the source-specific selected `InvalidToken`; an exceptional method exit by itself is insufficient.

The campaign chooses only observed SASL inbound I/O frames. Unique ordered fault plans use `IOException`, `EOFException`, `SocketTimeoutException`, and `ConnectException`, with at most eight faults in the default 80-trial budget. Only valid trials contribute production method/branch coverage and observed I/O feedback; new feedback schedules nearby plans ahead of unused deterministic seeds. Each completed trial atomically updates `result.json`, from which the table watcher redraws the aggregate row. An extension to 128 trials and ten faults is conditioned on new valid production coverage or stable I/O family near trial 80.

The completed campaign ran 80 unique plans and 228 requested fault events; all 228 matched and were applied. All 80 trials retained the same original request's post-final-fault target guard and passed the unchanged JUnit. Selected production branch coverage grew from 39 to 44 (+5). No trial produced the selected `InvalidToken`, another target exception, or a new-bug mark. Trials 73–80 added no valid production method/branch or I/O family, so the conditional extension did not trigger. The ledger records each trial's elapsed time and exact selector sequence.

This runtime uses the unchanged original JUnit, independent ByteBuddy probes, and JaCoCo coverage over five relevant production authentication classes. It does not use GraphChecker, prewoven classes, `region_skeletons`, `static_scope_map`, static aggregate, or closure data. Source snapshots are from HBase commit `97a51ab9e3cf9f9d21bf08c3b1e52c962579ef2b`.

## Local test harness compensation

The distributed test classpath mixed Apache Directory ASN.1 versions and omitted BouncyCastle and `hbase-http`'s test utility. The case runner places the matching Directory M20 jars and BouncyCastle 1.60 jars first. It compiles the original `KeyStoreTestUtil` source in this case; its only local behavior change is a path fallback when the original test class comes from a JAR instead of a Maven test-classes directory, so SSL files can be written under this case's class directory. The selected production class and original JUnit source are unchanged. Earlier setup-only failures are retained as diagnostics and are not counted as fault trials.

The final result, original logs, JaCoCo execution files, runner, source, and per-file SHA-256 manifest are packaged in this case's evidence archive.
