# HDFS-55 upstream I/O design audit (unexecuted)

**Status:** source-level design only. No JVM, healthy calibration, fault replay, or
original-versus-fixed differential was run for this design. It is not a
HDFS-17899 detection claim. Source pin: released Hadoop 3.4.3 commit
`9d50c6884666e794e45102260a4017bb31802e1b`.

## Viable stale-Balancer sequence

1. In an encrypted, block-token-enabled MiniDFSCluster, shorten the NN
   `BlockTokenSecretManager` key update interval `U` and token lifetime `T`
   through the test setters. Select a **newly generated** key `k` after this
   change, wait until NN promotes `k` to current and the destination DN
   successfully receives `k`, then construct the Balancer `KeyManager` while
   `k` is current. Its constructor's first `namenode.getBlockKeys()` must
   succeed (`KeyManager.java:70-89`). Startup keys cannot serve as `k`: their
   expiry dates were computed before the post-start setters.
2. Start one actor-scoped I/O outage at the Balancer background updater's
   `namenode.getBlockKeys()` call (`KeyManager$BlockKeyUpdater.run`,
   `KeyManager.java:177-185`, line 180). Each failed call throws a typed
   `IOException`; the updater catches it and retains its local current key
   `k`. The hook is restricted to that named Balancer manager, block pool, NN
   endpoint, and background updater actor. It does not change any key map,
   lookup result, or `DataEncryptionKey`.
3. Let the NN and destination DN continue normally. At the NN rotation that
   retires `k` (time `r`), the NN sets its expiry to `E = r + U + T`
   (`BlockTokenSecretManager.java:259-273`). At a later NN rotation **after**
   `E`, `removeExpiredKeys` removes `k`; a subsequent successful DN key-update
   command causes DN `addKeys` to remove its `k` and install the exported
   newer current key `k'` (`BlockTokenSecretManager.java:210-237`;
   `BPOfferService.java:779-785`). Observe these transitions and the actual
   DN map state. With `U=T=2000 ms`, the NN heartbeat monitor's 5000 ms loop
   (`HeartbeatManager.java:543-565`) governs real rotation cadence, so fixed
   sleeps or a two-rotation assumption are insufficient.
4. Hold the first Balancer move before its socket connection until that DN
   has `k` absent and `k'` present. The Balancer's stale local manager can
   generate a *new, locally unexpired* DEK from its old current key `k`:
   `generateDataEncryptionKey()` reads `currentKey` but does not check the
   `BlockKey` expiry (`BlockTokenSecretManager.java:526-536`). A later move
   by the same manager must take `KeyManager.newDataEncryptionKey()`'s
   `refresh=false` branch (`KeyManager.java:119-145`) and reuse the same
   `(k, nonce)` DEK. DN SASL must then reach its untouched
   `allKeys.get(k)==null` guard and native `InvalidEncryptionKeyException`
   (`BlockTokenSecretManager.java:547-558`), producing an `INVALID_KEY` wire
   response. Earlier block-token/SASL failures make the attempt inconclusive.

This is a candidate for the adapted encrypted one-node Balancer phase using
`TestBalancerWithEncryptedTransfer#testEncryptedBalancer0`/
`TestBalancer.integrationTest`, one mover and one concurrent DN move, and a
180-second JUnit bound. Test-only scheduling gates may hold a move; they must
not change key material or lookup outcomes. A healthy version must first pass.

## Differential and evidence requirements

The original 3.4.3 `Dispatcher.PendingMove.dispatch` catches the SASL
`IOException` and records a failed move without clearing the DEK
(`Dispatcher.java:391-411`). A positive original oracle needs repeated
same-manager `refresh=false` reuse of `(k, nonce)`, native DN missing-key
lookups and `INVALID_KEY` replies, zero cache clears, no move progress, and
the Balancer `NO_MOVE_PROGRESS (-3)` / JUnit failure
(`Balancer.java:759-766`; `TestBalancer.java:813-825`). A separately pinned
fixed replay needs the same predeclared updater outage; the fixed foreground
`km.updateBlockKeys()` call must succeed, followed by cache clear, a new
socket/DEK using `k'`, completed moves, and a passing JUnit. The HDFS-17899
fix retries once at that foreground boundary (fixed `Dispatcher.java:399-405`).
The older CrashFuzz DN-wire differential establishes this response behavior
under a **synthetic** `(keyId, nonce)` rejection; it is not evidence that this
upstream outage has run.

Trace NN generation/promotion/retirement/export of `k` and `k'` with actual
expiry times; every updater IOException; successful DN command delivery and
`addKeys`; the destination DN identity, block pool, and real post-get map
result; Balancer manager identity, guard result, key ID, short nonce digest,
and destination endpoint; and native IKE/`INVALID_KEY` plus move/JUnit
outcomes. Never log raw nonce or key material. Bind these observations by
event order and identity, not just matching key IDs.

## Feasibility limits of the staged DN command fault

The current `faithful55/dn-key-update-io-source.diff` is a real lost-update
door: `BPOfferService.java:779-785` receives `DNA_ACCESSKEYUPDATE`, and
`BPServiceActor.CommandProcessingThread.processCommand` catches its
`IOException` (`BPServiceActor.java:1434-1453`). The NN clears
`needKeyUpdate` when it emits the command, before DN application
(`BlockManager.java:1660-1666`). Missing the new next key and then its
promotion can therefore yield a naturally null DN lookup if no later DN
`addKeys(k)` intervenes. It does **not** by itself support the required fixed
oracle: the fixed Balancer's immediate NN refetch returns the same current
`k`, which the DN still lacks. Once the DN successfully installs `k`, the
original cached DEK can work too. A claimed fixed pass from this schedule
needs independent evidence that another accepted key became current and why
the old DEK still fails.

The staged post-start `U=T=2000 ms` recipe also leaves startup key expiries
unchanged: `BlockTokenSecretManager.generateKeys()` set them at construction
(`BlockTokenSecretManager.java:173-197`), while the config inputs are read in
minutes (`BlockManager.java:710-720`). Select and observe a later short-expiry
key as above. The upstream Balancer outage must span expiry and DN pruning;
the updater retries every `U/4` (`KeyManager.java:88-89,177-185`). Treating
that as **one persistent outage window** yields repeated `IOException`
events. It is not established that the current Mallory maximum of three
independent per-call faults can sustain this state until the original JUnit
fails. A separate fault-model admission or measured schedule is required.

Upstream context: [HDFS-17899 PR #8383](https://github.com/apache/hadoop/pull/8383)
defines Balancer clear-and-retry; [HDFS-17967 PR #8698](https://github.com/apache/hadoop/pull/8698)
is the later DataXceiver/StripedBlockWriter follow-up, not this Balancer fix.
