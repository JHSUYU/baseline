# SOLR-40 bounded actor-miss replay

This independent campaign starts from a fresh healthy run and selects fault
doors from its observed target closure. It uses the exact target call-throw
probe and pinned jars validated in v3b. It supplies no prior witness plan.

When a closure-selected single fault applies but the target check later runs
on another node, the scheduler queues up to two low-priority retries of that
same fault plan. Fresh plans run first. The result records
`selection_reason=actor_miss_replay` for these retries. The budget is 30
one-fault trials or 900 seconds; `run.sh` holds both Solr locks and resumes
the checkpoint. This tests the actor-routing gap observed in strict v4.
