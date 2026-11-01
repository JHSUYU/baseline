----------------------------- MODULE MCGuided1 -----------------------------
\* Phase 3 guided runs for Scenario 1 (MC_hunt_purge_restart.cfg).  Both
\* guides only remove states / transitions (CONSTRAINT, ACTION_CONSTRAINT),
\* so a violation found with them is a violation of MC_hunt_purge_restart.cfg.
\* base.tla and MC.tla here are byte-identical copies of the converged spec.
EXTENDS MC

\* Phase 2's guide: writer 2 starts only after writer 1 issued its purge and
\* had txn 2 acknowledged by a quorum (writer 1's committedTxId = 2).
GuideScenario1 == wr[2].pc # "init" => (fc.purge = 1 /\ wr[1].c = 2)

\* (a) Timing realism for the one-crash shape.  With connect retries
\* (Client.java handleConnectionFailure, 10 x 1 s by default) a call to a
\* down JN is refused only after the retry window.  Writer 2's calls start
\* after writer 1's purge, so if that purge is still retrying when the JN
\* restarts, writer 2's calls are too: none of them may be refused.
NoW2ConnectFail ==
    ~\E j \in JN : /\ ~jn[j].up /\ ~jn'[j].up
                   /\ ch[2][j].inf # NoReq /\ ch'[2][j].inf = NoReq

\* (b) The brief's two-crash shape: every JN is up (and stays up) once
\* writer 2 has started; the forgetting JN restarted before that.
GuideAllUp == wr[2].pc # "init" => \A j \in JN : jn[j].up
=============================================================================
