# HDFS-32 typed I/O admission

The existing TestDeleteBlockPool#testDfsAdminDeleteBlockPool healthy run
passed one JUnit and reached the selected DataNode.deleteBlockPool guard
twice on named dn0 epoch 0, both nonthrowing. The request audit binds the
first call to force=false and its expected file-content error; the second
uses force=true and succeeds.

The test calls refreshNamenodes to remove nameservice 2, asserts that one
offer service remains, then sends the two delete requests for its block-pool
ID. Refresh stops and joins the removed service. Its final actor cleanup calls
DataNode.shutdownBlockPool, whose synchronized manager removal deletes both
the offer-service list entry and block-pool map entry. The pretarget heartbeat
IOException is caught and retried; it does not retain or reinsert the map
entry. A client delete RPC exception can suppress a selected server call
instead of changing that guard.

BPServiceActor.join catches InterruptedException, but that is a different
fault type, and a prematurely retained offer service can fail the test's
one-service assertion before the selected delete. The alternate
testDeleteBlockPool intentionally expects the still-running guard exception
before refresh. No reviewed existing-test typed I/O exception changes the
selected predicate while keeping the target. A new workload or a distinct
source-backed transition is required before a fault pilot. The earlier full
package's static preflight passes; this receipt does not admit its fault plan.

Run python3 -B check_offline.py for the SHA-pinned source, healthy trace,
and request-order audit without a JVM.
