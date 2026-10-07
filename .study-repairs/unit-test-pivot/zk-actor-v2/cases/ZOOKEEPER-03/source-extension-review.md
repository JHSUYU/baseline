# ZOOKEEPER-03: additional I/O family review

The selected check is `SessionTrackerImpl.setOwner` at lines 327–330 in the
unchanged ZooKeeper 3.8.7 source (`9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae`).
`QuorumTest.testSessionMoved` (lines 193–238) creates one session and moves it
ten times across five peers. Each successor performs `setData` and a successful
`sync` before the next move. `Leader.revalidateSession` (lines 1730–1755) calls
the selected check while processing the follower's `REVALIDATE` packet. The
actor used by both completed campaigns is the actual leader peer 5 and the
same raw moved session, rather than a global callsite ordinal.

The first actor-aware campaign completed 480 original JUnit fault runs, 37 of
which retained that target after an exact same-actor fault. The separate
after-response campaign completed 186 runs and 27 retained the target. Its two
healthy traces show peer-5 client/server reads and writes and complete
`NIOServerCnxn.handleWrite.packetSent()` responses between selected guards.
The latter family was tested, including the third completed response after a
successful sync. The first stage reached its attempt cap and the second
exhausted its queue below 80 effective runs; neither observed a target
exception. These are two separate denominators; the 666 old
runs are never reclassified or replayed. See each stage's `evidence/` audit.

There are two possible new families, each requiring a *new* healthy calibration
and a small bounded pilot before any new fuzz budget:

1. **Quorum control-plane response.** `Learner.validateSession` (lines
   154–175) creates a `REVALIDATE` packet containing the session ID and
   `Learner.writePacketNow` (lines 197–209) flushes it. On the return path,
   `Leader.revalidateSession` queues its response to `LearnerHandler`, whose
   `sendPackets` loop writes records and flushes its buffered output (lines
   320–375). A true post-flush fault would have to bind the actual follower,
   leader peer 5, packet type, and raw session to that completed response.
   The current agent does not observe this completed quorum response, so no
   existing run proves it will preserve a later selected guard. A trace-only
   pair of original healthy JUnits, followed by at most ten fault runs if
   binding succeeds, is the concrete next experiment.
2. **Leader transaction log.** `SyncRequestProcessor.run` (lines 180–225)
   appends each write; `FileTxnLog.commit` (lines 376–410) flushes and may
   `FileChannel.force` it. A fault only after a successful force could qualify
   as completed file I/O, and its log directory would have to identify peer 5.
   An `IOException` propagates to the processor's top-level exception handler;
   under this synchronous `setData`/`sync` workload that may stop the current
   request and prevent the next selected guard. It is therefore lower priority
   than the completed quorum response, and cannot count without a pilot that
   demonstrates a later same-actor guard.

The existing epoch-file read/write hooks occur during peer startup in the
healthy trace, before the moving session and selected guards; some are
explicitly unbound. `QuorumTest.testSessionMovedWithMultiOp` (lines 256–281)
contains only one handoff, offering fewer same-actor target opportunities than
the selected ten-handoff test. Neither justifies reusing old runs or declaring
the 80-effective budget complete.
