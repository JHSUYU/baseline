------------------------------ MODULE MCGated ------------------------------
\* Phase 3 shaping run only: MC with a pruning state constraint (removes
\* states, adds none), so a violation here is also a violation of the cfg
\* it is copied from.  base.tla and MC.tla are byte-identical copies of the
\* converged spec/ files.
EXTENDS MC
\* Sequential failover: writer 2 starts only after writer 1 is active
\* (finished recovery).  Writer 1 may keep running afterwards.
SequentialFailover == wr[2].pc # "init" => wr[1].pc \in ActivePC \cup {"dead"}
\* Generalisation for NW >= 2 (Scenario 2/3 deep runs): each writer starts
\* only after the previous one is active or dead.
SequentialWriters ==
    \A k \in 2..NW : wr[k].pc # "init" => wr[k-1].pc \in ActivePC \cup {"dead"}
=============================================================================
