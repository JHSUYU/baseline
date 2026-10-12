# SOLR-14 v30 healthy path review

The existing `SplitShardTest#doTest` passed (1 JUnit test) and reached
`SplitShardCmd#split` line 165 three times on named `node1`. The exact
source file SHA-256 is
`995355f882947b528cedf9b7b38032f334afec74b5226d217f3f7828f2fb34f3`.
The SHA-bound v30 result is `946f08c9e52241080288913d64526f3287b8ff8366e26e017c334c34eb35a03a`;
its frozen-core audit is
`86b7950446eec391d8315669f2fbf556b71467879ea5a2a4c4b4edfa25198b03`.

The direct `SolrZkClient.exists` door at line 164 precedes each line-165
target check in the same split occurrence (event sequence 1683→1685,
9531→9533, and 9984→9986). The selected door injects
`KeeperException.ConnectionLossException` at the line-164 call site.
`split` declares `throws Exception` at line 106; the only nearby catch
at lines 149–154 handles `InterruptedException` from `getLeaderRetry`.
There is no catch around `exists` before line 165. Therefore a fault
injected at this direct door exits that split invocation before the
target check; a same-occurrence local-timeline fault pilot at this site
cannot establish postfault target retention. The line-130
`forceUpdateCollection` door is likewise outside a catch before the
target check.

The parent-region hook added three observed `region_parent` edges and
put 15 named doors in the target closure, but the frozen audit finds
zero observed-path doors and `report_gate_passed=false`. Keep this
healthy result as a mapping/causal-linkage gap; do not promote a full
fault campaign from this direct door. A later distinct upstream
server/background door would need a fresh healthy path proof and a
bounded postfault target-retention pilot.
