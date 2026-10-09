# Startup episode diversity queue policy

The original actor-qualified startup campaign preserved its calibrated
instrumentation digest `ec5a27c482919e86eb3eb82805abd44a9a32af45dcd6d89781e2b8178d91df30`,
case goals, ordered fault plans, and atomic checkpoint. A read-only audit near
94 completed plans found that 41 of HDFS-34's 44 effective trials ended at
startup episode 3, while 43 of HDFS-35's 44 effective trials ended at episode
1. The queue already contained actor-bound NN0 RPC points at the other
healthy-seed target episodes, but a deep sequence score of about 1,645 kept
winning over fresh-episode scores of about 999–1,220. The last eight
effective trials added no coverage branch or eligible I/O family.

`campaign_episode_diverse.py` changes only `pick()`. Every fourth selection
it chooses a pending actor-bound RPC plan on the least-tested target startup
episode, preferring an episode with zero **effective** same-actor postfault
trials. The original coverage, case-progress, depth, target-killing-file
penalty, and oldest-RPC exploration rules select the other plans. All existing
strict fault matching, target identity, JaCoCo accounting, max-eight/conditional
max-ten fault limit, and manifest-based resume logic remain in the unchanged
`campaign.py`. No completed ID is requeued or rerun.

The node1 old controller was archived before the switch as
`audit/controller_pre_episode_diversity_b65f.py`, SHA-256
`b65f23dd8b80bbdb5a6f09efac82e313771be22dcd8b094ade4ff70c5ccc913a`.
The new wrapper has SHA-256
`488e344b80824022472587772b22c63e2b47bae9f230b378f9fdbdae99d75bdb`.
Both files are staged under their new names on node1; the running old
controller file and process were not modified. The wrapper refuses to run if
the unchanged imported base controller has a different SHA.

Offline validation used the live checkpoint **in memory** without writing
to it. An in-flight sequence was returned unchanged. At a simulated
fourth-selection boundary, the policy selected queued one-fault RPC plan
`22a5c41d7858ffeb2336` at HDFS-35 episode 11, which had zero prior
effective same-actor trials, and popped exactly one queue item. Python
bytecode compilation also passed. Runtime handoff still requires a complete
original JUnit manifest boundary; after switching, audit the first resumed
plan, actor/endpoint/target receipt, and absence of duplicate attempt IDs.

## Live handoff and first diversity result

The [handoff receipt](episode_diversity_handoff.json) captures the pre-switch
checkpoint SHA, both controller SHAs, calibrated overlay SHA, and durable
manifest SHA. The old controller stopped at 06:37:37 UTC, after original
JUnit `f42acfa234e9d257e03d` exited with a complete manifest. The new
wrapper resumed it from that one `attempt-1` artifact and incremented the
completed sequence count from 97 to 98 without starting that JUnit again.
Its first newly executed plan `1cc5984f29eaebef0bb2` passed the original
JUnit in 73.713 seconds, injected the exact ordered faults, and reached the
same HDFS-34 actor afterward. The independent raw checkpoint audit passed.

At the first fourth-selection boundary (completed count 100), the policy
chose `32d0d57a268c694f5583`, a one-fault bound NN0 RPC plan on HDFS-34
startup episode 7. Episode 7 had zero previous effective HDFS-34 trials.
The original JUnit ran 2026-10-07 06:40:17.962–06:41:00.235 UTC in
42.273 seconds, exited 0, injected its fault exactly, and then reached the
HDFS-34 target on the same actor. The audit at 101 completed plans found
zero identity/ordering/coverage issues and zero novel target-exception
signatures. This adds one distinct target startup episode without altering
the 80/8 per-case budget or any completed trial.
