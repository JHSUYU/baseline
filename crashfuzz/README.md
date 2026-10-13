# CrashFuzz-style baseline for ad hoc checks

The current campaign uses an existing cluster JUnit test for each selected
check. The checklist supplies the exact target source location and test method.
It does **not** list I/O fault sites or coverage sites per case.

For each target, `core-fuzzer/rerun102_worker.py` asks the Soot selector in
`static-selection/` to inspect the corresponding system binaries. The selector
follows bounded callers and callees, field reads to possible writers, thread
handoffs, and RPC producer mappings. It writes one `soot-selection.json` with
selected methods, branches, and I/O callsites. System-wide binary paths and
the optional HDFS communication mapping are configured in
`core-fuzzer/prepare_case_selection.py`; they are shared by all checks in that
system.
For mapped RPC values, the selector also follows a bounded chain of callers
from the sender's value producer to an I/O call. This can select a transport
send that is several helper calls away from the producer. At the last hop it
admits direct I/O callers without expanding every remaining helper, so an
overloaded transport wrapper does not hide the sending operation.
For a check that explicitly throws its target exception, Soot also records
typed throw sites and the branches that can select them. The fuzzer uses the
selected source line to recognize the corresponding runtime `ATHROW`; a
passing JUnit result can still contain a target exception caught by its caller.
When a Soot throw unit has no matching runtime check probe, the fuzzer also
observes the nearest controlling branch of that same typed throw. This keeps
target reach and the exception oracle tied to the selected check without a
handwritten branch ID.

The ASM Java agent in `runtime-agent/` records only the selected I/O,
coverage, and check sites. It also registers embedded-cluster node identity
when a Solr controller finishes constructing.
A healthy run records the I/O points and code paths that actually execute.
The Solr runner enables nightly mode when the selected JUnit source uses
`@Nightly`; the JUnit launcher rejects assumption-skipped methods so a skipped
test cannot become a healthy seed. A campaign suffix also gives a replay its
own healthy trace and checkpoint.
If that run observes no selected I/O, the worker automatically retries the
Soot selection with a wider caller path and reruns the same JUnit method.
If the wider path still observes no I/O, it increases the coarse method budget
from 400 to 800 and repeats the selection and healthy run. The original and
expanded selections, healthy traces, and campaign checkpoints
remain separate so a resumed worker uses the selection that produced its trials.
The target branch can be absent in that run; the observed I/O points still
seed single-fault trials that may expose it.
`core-fuzzer/fuzzer.py` then mutates ordered exception plans, reruns the same
JUnit test, and uses new selected I/O and method/branch coverage to choose
later plans. A fault counts only when its full runtime identity matches and
the target check still executes afterward. Object identity hashes in generated
thread names and temporary cluster ports, including HBase's
`Listener at localhost/port` form, are normalized across JUnit runs;
the I/O site, actor class, and hit ordinal remain part of the match. Repeated
observations with the same normalized address also carry an occurrence ordinal.
For embedded SolrCloud tests, target-check events also record the serving
node when the request exposes its core container. This lets trial reviews
compare a watch fault's node with the node that executed the check.
When one is available, the scheduler reserves one trial in six for a later
observed invocation of a selected I/O callsite. It groups these invocations
by callsite, phase, and a coarse ordinal bucket so repeated early faults do
not consume the entire budget before state changes later in the JUnit run.
Another bounded slot samples an untried exact invocation when several calls
from a short JUnit fall in the same coarse bucket.
The scheduler counts callsite and phase together for site diversity: a trial
that fails a request before the RPC does not exhaust the distinct reply-loss
experiment after that RPC has completed.
One trial in seven is reserved for two observed lost replies from the same
actor and callsite when such a sequence exists, because the next successful
RPC can otherwise repair the first failure before the target check.
One trial in eight selects an observed three-or-more-fault descendant when
available, so overlapping fault effects get a bounded share of the budget.
One trial in nine selects a later, different I/O from the same runtime actor
after an earlier fault, to test whether a subsequent read or RPC repairs the
state before the target check.
If every fault in a multi-fault plan matches but the final fault lands after
the target check, the runner retries that exact plan a bounded number of times
to account for callback and request-routing order in the original JUnit.
The healthy trace also identifies I/O observed shortly before a target check.
One trial in five is reserved for these near-check I/O observations when any
remain; other trials continue to explore the broader Soot-selected scope.
An I/O observation with unresolved actor identity is excluded from the fault
queue and does not count as a replayable healthy I/O point when deciding
whether to widen the Soot selection.
For HDFS embedded-cluster DataNode actors, the agent adds the stable `dataN`
slot from `dfs.datanode.data.dir` to the runtime address. If that slot cannot
be resolved, the trace records `ACTOR_IDENTITY_GAP` and the fuzzer does not
queue that observation as a fault point. This prevents a fault intended for
one DataNode from matching another DataNode with a similar thread name.
For embedded SolrCloud tests, the agent associates each `ZkStateReader` with
the stable `nodeN` slot in its controller's Solr home. Alias watch callbacks
then retain a distinct node identity even when the `zkCallback` thread pool
number changes between JUnit runs. A callback without a resolved node slot
is recorded as an identity gap and cannot receive a fault selected for a
different Solr node.
ZooKeeper calls can receive a
`ConnectionLossException`; other selected calls receive an `IOException`.
An observed target exception is a candidate for replay and source review.
The HBase runner supplies the original test-only SSL utility needed by its
Kerberos cluster JUnit and pins matching Directory API dependencies.

New Soot selections enable two phases for eligible synchronous RPC callsites:
`before` runs just before the call, while `after` runs only when the call
returns normally. An `after` fault models a completed RPC whose response is
lost to the caller; it does not undo the remote operation. The agent excludes
constructors, asynchronous callback/future APIs, and ordinary local I/O from
post-call injection. Phase is part of each observation and replay identity,
with independent hit and occurrence ordinals for each phase. Generated plans
write the phase explicitly. Post-call plans use only a transport-level response
loss exception; typed callee rejection variants apply only before the call.
Older selections without `post_call_rpc_enabled`
observe only `before`, and older plans without a phase still match `before`.

## Run a selected check

```sh
cd /users/ZhenyuLi/baseline/crashfuzz/core-fuzzer
python3 rerun102_worker.py \
  --system HDFS \
  --checklist ../../data/crashfuzz/checklist102.json \
  --result-root /path/to/isolated-results \
  --case-id HDFS-01 \
  --max-trials 80 --max-faults 10
```

`--system` accepts `HDFS`, `HBase`, `Solr`, or `ZooKeeper`. Omit `--case-id`
to process the system's checklist. Workers can divide one system with
`--shard-index` and `--shard-count`. Each case has its own atomic checkpoint;
restarting a worker resumes unfinished work without replaying completed
trials. A case lock prevents overlapping workers from replacing each other's
summary or setup state. A check without an original cluster JUnit test is marked
`no_cluster_test`.
Completed noncandidate trials compress every attempt's trace and JUnit log,
including attempts retried after an unmatched fault point. Candidate traces
stay uncompressed for review.

The current three-node run writes a per-check summary beside each result and
aggregates the 102 entries in [`../data/crashfuzz/static102-rerun.tsv`](../data/crashfuzz/static102-rerun.tsv).
The table records the exact check location, selected JUnit, time, fault
trials, strict injections, healthy and post-fault target reach, lost-target
trials, new method and branch coverage, and candidate count.

`healthy_target_reached` refers to the exact selected bytecode site. When
that site is the `throw` inside a guard, `False` in the healthy run is expected
and does not imply that the enclosing guard was never evaluated.

`cases/`, the older shared adapters, and `entrypoints.json` preserve the
previous case-specific campaign and its reproduction records. The Soot
selected campaign above does not import their per-case I/O or coverage lists.
