# Reusing Solr ZooKeeper actor identity

The V2 probe exposes two narrow hooks that other embedded Solr JUnit campaigns
can reuse. The agent has no dependency on `ShardSplitTest` for these hooks;
only the target-check instrumentation and stable-role resolver are case
specific.

1. In `ZkController.<init>`, immediately after the `PUTFIELD zkClient`, invoke
   `Probe.bindServerClient(this.zkClient, this.nodeName,
   this.cc.getSolrHome())`. The signature is
   `(Object client, String rawNodeName, String solrHome)`. Early operations
   before this assignment remain unbound and cannot be selected.
2. At the entry of each instrumented instance `SolrZkClient.lambda$...`
   operation, invoke `Probe.nativeEntry(this, path, methodNameAndDescriptor)`.
   The receiver is essential. Reading only MDC or a ZK path does not establish
   which Jetty/reader issued the I/O.
3. Assign a stable actor key from the original test's server role. For
   `BaseDistributedSearchTestCase.createServers`, the Solr home ends in
   `control` or `shardN`, so this implementation uses `JETTY/control` and
   `JETTY/shardN`. Other cluster test frameworks must derive their own role
   from their **original test setup** and prove it is stable in two clean JVM
   runs. Do not use the changing TCP port or `System.identityHashCode` as a
   cross-run selector.
4. The selector and per-site hit ordinal must include
   `(operation, caller, logical source, actorKey, resource)`. Emit raw rows with
   `actorKey`, raw node name, `clientIdentity`, Solr home, and MDC node/core.
   Mark any unknown client or unknown home role `UNBOUND`; never generate a
   fault plan from it. A planned fault on an unbound actor must fail closed.
5. Record the receiving actor of each target check separately. A post-fault
   target counts only when its logical child and receiving actor match the two
   healthy seeds. A faulted I/O actor may differ from the target receiver;
   that relationship is explicit in the raw trace and cannot be inferred from
   collection-wide ZK path names.

`smoke_transform.py` verifies the bytecode hooks on the original Solr 8.11.4
classes. `smoke_actor_match.py` executes the same I/O signature through two
bound clients and proves the wrong actor cannot consume a planned exception.
`calibrate.py` checks raw client bindings, target child roles, and stable exact
selectors in two clean original JUnit runs before `fuzz_v2.py` can initialize.
For another Solr version, re-check the actual `SolrZkClient` lambda methods
and `ZkController` field descriptors; copying an ASM hook without validating
the transformed bytecode can silently miss I/O.
