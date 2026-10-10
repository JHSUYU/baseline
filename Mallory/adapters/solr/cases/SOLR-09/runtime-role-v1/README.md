# SOLR-09 runtime command binding, staged full campaign

The unchanged Solr 8.11.4 cluster JUnit is
`DeleteReplicaTest#deleteReplicaAndVerifyDirectoryCleanup`. The pinned prior
healthy trial passed one test and observed the exact line-277 `deleteCore`
target on a named Overseer actor. It also observed the typed
`OverseerCollectionMessageHandler#waitForCoreNodeGone@434` door before that
check in the same `deleteCore` occurrence. Its `TimeoutException` is caught
by `waitForCoreNodeGone` and returns false, allowing the `DELETECORE` fallback
and second wait. The prior one-fault trial did not inject: the fixed node4
plan missed the actual node2 actor. The raw target still executed. See
`../source-admission-v1/healthy-audit-node2-lane3.json` and
`../source-admission-v1/unmatched-pilot-audit-node2-lane3.json`.

The case-local agent here resolves a `delete-replica-deletecore` role only at
that exact typed door, while the current top region is the exact
`DeleteReplicaCmd.deleteCore` method and the Solr adapter has registered a
concrete node/epoch. It emits the physical actor and command occurrence on
the observed, matched, and applied events. Unnamed actors, unrelated methods,
and a mismatched occurrence cannot receive a role ordinal. The plan uses
`{site, role, role_ordinal}` rather than a fixed node or a node wildcard.
The unchanged v38 Solr adapter supplies lifecycle node binding; the modified
agent and campaign core are confined to this directory.

`config-full-node2.json` stages a fresh healthy seed followed by up to 80
fault trials, 3600 cumulative trial seconds, and at most three faults per
trial. The selected exception is `java.util.concurrent.TimeoutException` at
the typed wait door. The campaign can stop with a terminal queue or budget
status. Graph and postfault path evidence are recorded as outcomes; they are
not admission conditions under the current completion rule. An exact target
exception is not claimed from the healthy run or unmatched pilot.

`run_full_node2.sh` requires a case-local `admission-full-node2.json` GO
receipt with `solr31_terminal=true`, matching config and runner SHA-256, the
intended output, host node2, and a SHA-pinned terminal SOLR-31 full result
(`solr31_terminal_result_path` and `solr31_terminal_result_sha256`). It also holds the node2 lane3 and shared
source locks. No such receipt is staged here. The new agent's role event has
passed unit tests but has **not** yet been observed in a fresh cluster JUnit;
the campaign healthy seed must supply that runtime proof before any fault
trial is queued. `run_campaign.py --preflight-only` checks pinned inputs
without starting a JVM.

Case-local verification on node0: `mvn -q test package` passed, including two
registry tests and one probe integration test that applied the exact typed
exception with a physical node/epoch/occurrence receipt;
`python3 -m unittest -q test_campaign.py` passed; and
the no-JVM campaign preflight passed. The built agent SHA-256 is
`518030007d63965b483c4875d40b104701be6bf32a845eafe655e54ef06d23f7`.
