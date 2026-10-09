# SOLR-34 original source review

The unchanged original test is Solr 8.11.4
`org.apache.solr.search.TestCoordinatorRole#testSimple` at revision
`e27f44e3d78dfcec230c97e0a1240e3751daeff9`. Its source SHA-256 is
`2e2c6a24b8f2ea37bb1dc4b95842e7974b166e000acf8393ba7d1342bddb59b3`.
The test starts four ordinary Jetty nodes, creates `test_coll`, indexes ten
documents, starts a fifth coordinator Jetty, queries through it, and checks
the ten results, synthetic collection, and coordinator replica.

The exact target is the newly constructed `SolrException` at
`CoordinatorHttpSolrCall.java:143` when `syntheticColl` is still null after
`createColl(...)` and `createException` is null. The rethrow of an earlier
`createException` at line 140 is a separate path. The V2 recorder observes
the guard at line 138 and the two throw sites separately. A JUnit failure,
an arbitrary SolrException, or the line 140 rethrow alone cannot count as the
SOLR-34 target.

At the start of the original `getCore(Factory,HttpSolrCall,String,boolean)`
method, the adapter reads `solrCall.cores.getZkController().getNodeName()` and
`solrCall.cores.getZkController().getZkClient()`. It records both the physical
coordinator node and the exact live `SolrZkClient` object. At retry-internal
native ZooKeeper operations, it records the receiver (`this`) of that same
client class. Fault eligibility requires receiver identity (`==`) with the
target client's object, the same request's `getCore` stack and thread-local
binding, an exact actor role, source, site, resource, and hit ordinal. Other
Jetty clients remain visible in the raw trace but are ineligible.

The identity gate is checked both in an offline wrong-client fixture and by
parsing every actor-labeled I/O event against the target entry's client
identity and physical node. Faulted trials require every planned fault to
apply at its ordered site and the exact guard or target throw to occur after
the last applied fault before they count as effective.
