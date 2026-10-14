# Original seed Jimple snapshot release

`ScopePlanner` captures a clone of every application method body at `wjtp`,
indexes the bodies it needs for Mallory's later site translation, then clones
the captures into Soot's active bodies before invoking the original
GraphChecker seed. The original seed reads the restored active bodies. The
capture map has no subsequent reader, so `jtpBodies.clear()` releases its
references before the expensive backward analysis. In particular, generated
protobuf bodies skipped by the translation index need not stay alive through
the seed. The index still owns all bodies it uses, and Soot owns the restored
clones. No graph edge, worklist rule, fault site, or runtime hook changes.

## Focused equivalence gate

An isolated Java 8 fixture used one compiled class with a static state read
and an `IOException` controlled by `if (read() == null)`. It selected the
branch and exception at source line 6 in original GraphChecker seed mode,
with loop bound 3. The class source SHA-256 was
`870c507a155ef799d581061e1088c1ea5a7c9f4365029ae0206f91e01c1e0c12`;

```java
package fx;
public final class Check {
  static String state;
  public static String read() { return state; }
  public void check() throws java.io.IOException {
    if (read() == null) throw new java.io.IOException("missing");
  }
}
```

The Java 8 compiler used `-g`. The fixture's original seed input selected
`fx.Check.check` line 6 and set `original_graphchecker_seed=true`. The same
input JSON was used for both runs; its SHA-256 was
`fccb0d2a895235d937eadf203a8219bfde95cf5f62098b3099e09427df3a7a7c`.
Both runs used original-engine JAR SHA-256
`6cc21b1df12f489229dd10bc6e7d9e6488f76b8105409b3e8cb18510cb55f58e`.
The baseline planner JAR SHA-256 was
`71570d91c50b5a679414e23de8cee2339d32170ce3dc698c32f4d7cc36238122`;
the snapshot-release planner JAR SHA-256 was
`63d5930e935a4ceed4e042698d916fed293ffb99cd8dcb32588641fdd5b52768`.

All 12 outputs matched **byte for byte**, including the candidate graph,
region skeletons, original and translated scope maps, weave manifest, and
analysis JSON. Sorting their relative paths and SHA-256 values, then hashing
the newline-terminated manifest, gives
`b9f585dbdcf906b01b966addafde25fa2edbe6b9d12f4920a7ae5d1418f1fd99`
for either run. Only `planner.log` differed because it records elapsed time.
`mvn -q -Dtest=ScopePlannerTest test` passed 26 tests.

The fixture's three indexed methods do not measure the memory benefit on
HDFS or Solr. A versioned large-run comparison should record peak RSS and
old-generation occupancy; the current pinned campaigns must remain untouched.
This patch reduces retained snapshots but does not change the cost of the
original `ReturnOnlyFormals` fixed point.
