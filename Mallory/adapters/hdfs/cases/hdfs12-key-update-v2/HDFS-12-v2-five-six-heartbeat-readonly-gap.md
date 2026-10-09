# HDFS-12: read-only review of five or six consecutive heartbeat faults

Decision: **no max6 pilot with the unchanged `TestEncryptedTransfer#testLongLivedClient[0]` workload.** The existing traces support a missing-key interval if heartbeats 5–10 are suppressed, but do not support reaching the selected `BlockTokenSecretManager.retrievePassword` missing-key guard during that interval. No five- or six-fault JUnit was run.

The test enables encrypted data transfer and block access tokens, sets the NameNode key-update interval and token lifetime to 2 seconds, completes its first read/checksum, sleeps 15 seconds, then reads/checksums again (`TestEncryptedTransfer.java:99–103, 300–321`). Parameter `[0]` has no trusted-channel resolver (`:84–92`), so the second read uses the encrypted SASL path. The DataNode heartbeat is scheduled about every 3 seconds in the observed trials; its `sendHeartBeat` site schedules the next heartbeat before its RPC (`BPServiceActor.java:537–563`). The loop catches the injected `IOException` and continues (`:703–743, 786–790`). A later successful heartbeat can enqueue `DNA_ACCESSKEYUPDATE`, whose handler calls `addKeys` (`BPOfferService.java:774–786`). Successful registration can also install exported keys (`BPOfferService.java:414–432`), though no such later registration was observed in these three trials.

| Existing trial | Exact faults on `hdfs-cluster-2/dn0` | Subsequent key delivery and selected lookup |
| --- | --- | --- |
| One fault | heartbeat ordinal 6 | Ordinal 5 installed selected key `755636452`; encrypted-key read and `retrievePassword` both used that key; no selected throw. |
| Two faults | ordinals 5, 6 | Ordinal 7 installed keys before the later read. The selected key `741424758` was installed before both encrypted-key read and target check; no selected throw. |
| Three faults | ordinals 5, 6, 7 | Ordinal 8 installed keys around 15.00 s after trace reference; ordinal 10 installed selected key `1246626942` at 20.995 s. The NameNode minted its token at 23.950 s. The DN read the *same* keyID for encrypted SASL at 23.963 s and for `retrievePassword` at 23.969 s; both succeeded. Ordinal 11 began at 23.985 s. |

Five faults at ordinals 5–9 leave ordinal 10 to install the selected key about 2.97 seconds before the observed target. Six faults at ordinals 5–10 would suppress that install, but the first encrypted SASL read occurs only about 16.6 ms before ordinal 11. More decisively, the selected read in all three recorded trials uses the **same keyID for `retrieveDataEncryptionKey` before `retrievePassword`**. In the three-fault trace those are events 442 and 447, both key `1246626942`. `SaslDataTransferServer.receive` selects `getEncryptedStreams` for this test (`SaslDataTransferServer.java:114–121`); its SASL password callback calls `retrieveDataEncryptionKey` (`:182–190, 268–279`) before the later block-token password check. Both look up `allKeys`, and a missing encrypted key throws `InvalidEncryptionKeyException` (`BlockTokenSecretManager.java:545–558`). `DFSInputStream.blockSeekTo` catches that exception, clears the client encryption key and retries (`DFSInputStream.java:653–664`). The next heartbeat may then install the key before the retry reaches the selected target.

Thus six consecutive heartbeat faults may expose an **earlier encrypted-key failure**, or timing may let ordinal 11 replenish the DN first. The current source and traces do not establish a retained selected `retrievePassword` occurrence with an absent block-token key. This is a workload/earlier-guard gap, not evidence that the HDFS selected exception is impossible under every schedule. A justified future attempt needs a source-backed workload where the encrypted SASL key remains usable while a different newly minted block-token key is absent, or a measured read overlapping rotation before key delivery, followed by a fresh healthy target and postfault causal audit. Merely increasing the same heartbeat count does not supply that proof.

## SHA-bound evidence

- Source revision: `9d50c6884666e794e45102260a4017bb31802e1b`.
- One-fault negative receipt: `HDFS-12-v2-one-fault-negative.json`, SHA-256 `2346b74f1148794c82332e48f8479e2093f598ca7e6c61b7d91a23b2378c076b`; trace SHA-256 `13d60f00b77de0528eb4556bf873fa7faf06b8e634d838d9fcfd76c3e7d26f18`.
- Two-fault negative receipt: `HDFS-12-v2-two-fault-negative.json`, SHA-256 `46afb40637c7697af9d5e1fe9dd73b0126d982414f0a981e81fdd1a3b806c1c8`; trace SHA-256 `c473583ef339f05f932977e1756cbf0016ae5ad5bb27fb1dab1a0a68ea659abb`.
- Three-fault negative receipt: `HDFS-12-v2-three-fault-negative.json`, SHA-256 `a11c25df3050ef5428cb1d81656c4cbd3b21adf8fcd0e62986c522a1bc12b66f`; trace SHA-256 `1b7c8eb0e5475965402a7d9054a758e212c7fdd3bdd9aa21756ff5a26f6dc2dd`.
- `TestEncryptedTransfer.java`: `8272862b11d4a645ffa6029c3f1462a14dcfce7b873815fcccc949d74a4bc0a5`.
- `BPServiceActor.java`: `fbcb03b86822e71e451242142752706b61c3f3f096d0219f5d90344bc59bb833`.
- `BPOfferService.java`: `21c5c65c5c023cc004aee8ca4814037de86de811db0e7960cb17c2909ccb8294`.
- `SaslDataTransferServer.java`: `a4c6deff36933bb0eb4c89c3b218a355f88297ddd434572b41fcd38e43418c97`.
- `BlockTokenSecretManager.java`: `d6f2dd33b2cb82484ab52262a05bf4445113e168de08479af00ad93969911957`.
- `DFSInputStream.java`: `e61685e14fcda7c598fc76299cbdbd1677e2ef5c52c75a20d8cc4fa0f914d151`.
