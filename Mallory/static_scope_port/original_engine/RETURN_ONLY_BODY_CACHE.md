# Bounded parsed-body cache for the original seed

The HDFS11 original-engine static run remained in `ReturnOnlyFormals.Body.read`
and `Body.closure` after 17 minutes, with roughly 9.4 GiB resident memory.
`ReturnOnlyFormals.compute` previously parsed every indexed row of a method
again whenever its summary was invalidated. The cache retains the parsed
adjacency for recently used methods and incorporates newly indexed rows into
an existing entry. It retains at most 32,768 rows across at most 64 methods;
evicted methods are rebuilt from `rowsByOwner` when needed.

The cache holds only the method's row-derived adjacency and fixed origins.
Each summary computation still copies the origins, computes both closures, and
asks `linked(call)` for the callee's **current** return-only classification.
The original per-method version and global-turn invalidation remain in place.
In particular, a callee acquiring an effect can still remove a previously
available return-only call-result link.

The focused `ReturnOnlyFormalsBodyCacheTest` compares cached, evicting, and
uncached modes across exactly that callee-effect transition. `mvn -q test
package` passed in `original_engine`. An 88-method original-seed fixture
produced 12 byte-identical static output files with and without the cache,
including its graph, region, scope, and weave artifacts. Only planner log
elapsed time differed. The common artifact manifest SHA-256 was
`512d187a59bff86c1b68b27b9354dfd967fb49168a3e74b9150d04a05a6cbf44`.

This equivalence fixture does not establish a memory or runtime improvement
for HDFS11. The cache removes repeated parsing but does not bound fixed-point
work or closure traversal; a separately pinned HDFS11 static run must measure
both time and memory before it can be adopted for formal experiments.
