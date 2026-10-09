# HBASE-11: completed region transition reported as failed after a lost RPC response

**Status: reproducible client-level candidate; correctness and novelty unconfirmed.** The selected server guard in `AssignmentManager.preTransitCheck` behaves as written. The question is whether the `Admin` API should report the completed transition as a nonretryable region-state error after its automatic retry. The injection deliberately models a lost successful RPC response; the synthetic timeout itself is not a bug.

## Original JUnit and exact sequence

The unmodified HBase 2.6.6 `TestRegionMove.testDisableAndMove` calls `admin.unassign(regionName, true)` at `TestRegionMove.java:105` before checking that subsequent moves fail. The case-local ByteBuddy hook matches exactly `RPC_RESPONSE|unassign#1|hbase.pb.MasterService.UnassignRegion|ordinal=1` and replaces the successful client-side RPC result with one `SocketTimeoutException`. The trace reports `originalException=none`; the request was delivered.

1. The first `UnassignRegion` reaches `preTransitCheck` with the selected region in `OPEN` and no active procedure. The check returns normally.
2. The region server closes the region; `RegionStateStore` writes `CLOSED` to `hbase:meta`. Both `CloseRegionProcedure` and the parent `TransitRegionStateProcedure UNASSIGN` log `state=SUCCESS` **before** the response hook fires.
3. The client receives the injected timeout. `HBaseAdmin.unassign` retries the same region request using `executeCallable` and `RpcRetryingCallerImpl`.
4. The second `UnassignRegion` reaches the same guard with the region in `CLOSED` and no active procedure. The B2 expected-state check throws `DoNotRetryRegionException`, as designed for a duplicate transition.
5. `HBaseAdmin.unassign` propagates that exception to the original JUnit call at line 105. The JUnit fails before reaching the later expected move assertions.

The exact sequence reproduced in **two independent clean runs** of the same selector: `replay_unassign.log` (49.18 s) and `replay_unassign_002.log` (46.41 s). Each run injected exactly one response timeout after a successful underlying RPC, reached B2 on the retry, and produced `JUNIT found=1 succeeded=0 failed=1`. Full logs are on node1 under `cases/HBASE-11/independent/`; paths are recorded in `independent/client-candidate.json`. These diagnostic replays are excluded from the 80-trial campaign budget. Original shared trial `HBASE-10/gf_0001` independently showed the same sequence. A secondary clean replay of `AssignRegion` response loss (`replay_assign.log`, 50.19 s) showed the symmetric `CLOSED -> OPEN` transition, duplicate assign rejection, and JUnit failure.

The replay plan is [`independent/replay-unassign.plan`](independent/replay-unassign.plan). On node1, the existing case-local runner can reproduce it with:

```sh
cd /users/ZhenyuLi/baseline/crashfuzz/cases/HBASE-10/independent
./run.sh run hbase11_repro ../../HBASE-11/independent/replay-unassign.plan
```

Use a fresh suffix for each run so the embedded cluster has separate temporary files and ports. The plan hashes the stable RPC response family plus its first occurrence; it does not depend on a fixed socket port.

## Source review and contract boundary

- `HBaseAdmin.java:1594-1618` rebuilds `AssignRegionRequest` or `UnassignRegionRequest` from the same region inside the retried callable; `HBaseAdmin.java:3170-3180` uses `RpcRetryingCallerImpl.callWithRetries`.
- `MasterRpcServices.java:648-675,1755-1784` delegates to `AssignmentManager`. `AssignmentManager.java:811-818,839-854` waits for each transition procedure to finish. The target `preTransitCheck` throws `DoNotRetryRegionException` when the second request sees the post-transition state (`AssignmentManager.java:754-764`).
- `Master.proto:102-116` carries a region, plus optional flags, but no operation nonce. `RpcRetryingCallerImpl.java:98-116` retries the initial timeout and fails fast on the duplicate request's `DoNotRetryIOException` subclass.
- `Admin.java:1158-1169` documents `IOException` for remote or network exceptions. A genuinely lost response leaves client-side completion ambiguous. This contract may permit the observed failure even though the server completed the operation. The mismatch between completed mutation and reported nonretryable region-state error warrants API review, but is **not yet a confirmed new bug**.

Related Apache issues [HBASE-11659](https://issues.apache.org/jira/browse/HBASE-11659) and [HBASE-28405](https://issues.apache.org/jira/browse/HBASE-28405) involve other region transition contexts and do not establish a duplicate or novelty here. The original source tree reviewed is commit `d5f63f523c065f963992ea4e74db268d17816631`.
