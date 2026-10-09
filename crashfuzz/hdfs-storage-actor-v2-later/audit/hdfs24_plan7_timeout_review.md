# HDFS-24 plan 7: original JUnit time budget, not selected target exception

The node1 `upgrade-constructor` campaign completed plan `915970dc94a14943d08f`
at 2026-10-07 10:21:35.265374 UTC. Its six ordered `Client.getRpcResponse`
`IOException` faults all matched the same bound actor
`episode=6/dn=1/dirs=dfs/data1/peer=NN0`. The selected
`BlockPoolSliceStorage.doTransition#L415-IFGE` check ran twice after the last
fault on that actor and volume. It threw **zero** selected target exceptions.
The independent raw checkpoint audit reports seven distinct strict sequences,
six effective HDFS-24 trials, zero identity issues, and no novel target throw.

The original `TestDFSUpgrade#testUpgrade` JUnit returned 1 after 76.697 wall
seconds. Its sole failure is `test timed out after 60000 milliseconds`, from
the test's own `@Timeout(value = 60)` at `TestDFSUpgrade.java:226` (source SHA256
`73e9f3af72fa9e55e8a9013da927315a1c50db86442498c8ac8b5ce44c85e766`).
The log reached `***TEST 22*** Normal NameNode upgrade: numDirs=4` before
timing out. The preceding `IncorrectVersionException` is at source line 367
inside `startNameNodeShouldFail`; the JUnit log explicitly says
`Successfully detected expected NameNode startup failure`. The two healthy
JUnit runs passed in 44.120 and 40.406 wall seconds. Strict fault plans with
one through five faults passed at 49.690, 55.683, 61.155, 65.361, and 70.056
seconds, respectively. The sixth fault crossed the test's method time limit.
This is a non-target timeout observation, not evidence of an HDFS-24 target bug.
The pause was at a complete plan boundary: `in_flight=null`, seven completed,
six effective. No plan is rerun or removed.

Immutable node1 raw files for `runs/915970dc94a14943d08f/attempt-1`:

| File | SHA256 |
| --- | --- |
| `manifest.json` | `e49f31f5c8684c00ff8d6f96a89cb228416f7713ff2d9845ef21f0bcff3a7cdc` |
| `junit.log` | `547d12627b5cf9b9660826267b62b37f4900ec2b81f67ede62fc05cfeb3dc8bb` |
| `runtime_trace.jsonl` | `2061fdaa8a168a9544cb01ba0f5dd75da21732e0061ff0563f126f024896217e` |
| `jacoco.exec` | `f4d462b0ab7ed7a482d0757e60260d63a603e7fbad7d874a9bcf46cafed24cb3` |
| `faults.tsv` | `3c00fd6b8a8929a414679d0db330f35ac57e31289504ab38e61029a2ecefafe5` |

The queue at the pause had 89 plans: 52 depth one, six each at depths two
through six, and seven at depth seven. We changed **selection order only** in
`campaign.py`, from SHA256 `def5991586e4fcda884a636a72990450dba33cd718644fa28aeec5dfdb5217ac`
to `325d5399add30dabb20d4f6919b1b2ed181d79247c792924f6fc90ab0cecfdb2`.
It now favors shallow plans after a non-target JUnit failure, samples an
unseen actor every seven completions where available, and retains a bounded
deep RPC sample every twelve completions below the observed failure depth.
The 80 effective / max 8 fault goal and conditional 128 / max 10 goal, target
oracle, actor identity, existing checkpoint, and original JUnit remain fixed.
An offline simulation from the frozen checkpoint selected depth-one bound RPC
plans at the next three positions and sampled a depth-five RPC at position 12;
it also reached actor episodes 10, 4, and 15 by position 15. Compile and raw
checkpoint audit passed before resumption.

## Resume and locked resource gate

The first resumed launcher reached the shared start lock at 10:27:47 UTC but
found five existing Java processes, so it produced `resource_gate_pause` for
plan 8 without running a JUnit or changing the checkpoint. We then changed
only `guarded_locked_campaign.py` to keep its tmux alive, archive each gate
receipt and raw `launch_gate.json`, and retry every 30 seconds at the same
complete checkpoint. The original failed receipt is preserved under
`gate-pauses/locked-plan-0008-initial*.json`. The corrected supervisor is
tracked by commits `1ddf0a64dd87f193307c7f3384948e506dc6b5a5` and
`20a3b70e0b0db689fb2bf2fd158d33290a756eac`; no target instrumentation,
fault plan, prior result, or original JUnit changed.

At 10:31:52 UTC, the locked gate observed four existing Java processes and
16,861,323,264 free bytes, then launched the next original JUnit. Plan 8
`0953bb12dc6202dc410b` used one exact episode-10/DN1/NN0 RPC fault. It
passed in 49.395 seconds, with two same-actor postfault HDFS-24 checks.
One selected `IOException` matched the exact healthy signature
`episode=10/dn=1/dirs=dfs/data1`, `upgrade=false`, `dfs/data1` in **both**
healthy seeds; the independent audit reported eight strict, seven effective,
zero issues and zero novel target signatures. The supervisor continued from
plan 9; no old plan was repeated.
