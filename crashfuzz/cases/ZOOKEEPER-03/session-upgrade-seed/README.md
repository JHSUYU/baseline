# Independent original quorum seed for ZOOKEEPER-03

The archived 63-plan pre-I/O queue continues independently. This seed checks
whether a different original five-peer cluster test can reach the **same**
`SessionTrackerImpl.setOwner` guard with a more useful actor-bound I/O window.
The unchanged `SessionUpgradeTest#testUpgradeWithEphemeralOnFollower` creates
five ephemeral nodes to upgrade a local session, disconnects, and reconnects
with the same raw session ID through another follower. Its `QuorumBase` setup
starts five peers. The original test/class source commit is
`9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae`.

The oracle needs a narrower identity than source line alone. In
`LeaderSessionTracker.setOwner`, a failed `localSessionTracker.setOwner` call is
caught and followed by `globalSessionTracker.setOwner`. The local throw can
therefore be **expected healthy behavior**. The isolated `UpgradeBridge`
accepts a target guard only when the actual `SessionTrackerImpl` receiver is
the leader server's `globalSessionTracker`, the raw session matches the
test's initial and reconnected handles, and the test is between the reconnect
and explicit `close()`. It records ignored local guards separately. The
target owner must still be the leader's local owner or a bound forwarding
`LearnerHandler`, and the guard's branch must be `present-open` in healthy
runs. No target exception is called a bug without a faulted same-identity
trace, unmodified-JUnit replay, and source review.

The original method's compiled bytecode stores its initial ZooKeeper handle
at slot 9, the upgraded raw session at long slot 10, and the second handle at
slot 9. The adapter binds the initial handle after its constructor, binds the
raw ID at source line 180, begins the selected reconnect phase at line 182,
binds the second handle after its constructor, and ends the phase before the
`close()` at line 192. The first and second constructor descriptors are
checked; later constructors for the intentionally closed session are excluded.
The offline ASM smoke confirms exactly six test hooks and one target guard and
throw hook on the original `.class` files. `build_upgrade.py` records the
agent, generic actor registry, ASM, and original class SHA values.

`run_upgrade_health.py` stages two no-fault original JUnit executions on
node1. It uses the shared `jvm-start.lock`, requires fewer than four existing
Java processes and at least 10 GiB free disk at each launch, and reserves
slot 15/16 (ports 30065–31410), separate from the 63-plan queue's slot 14.
The seed is usable only if **both** original JUnits pass with five bound peers,
one leader, one raw upgraded session shared by initial/reconnected handles,
the reconnect phase boundaries, at least one selected global target guard,
no selected target throw, and no binding error or fault. The raw session IDs
must be independent across healthy runs. If any condition fails, this test is
recorded as unavailable for the selected check; no fault pilot follows.

If calibrated, a separate bounded pilot can choose up to ten **observed**
actor-bound I/O selectors occurring after raw-session binding and before a
later selected global guard. Client socket reads receive priority because
they were the only family with target retention in the previous test's
ordered-child traces. Every pilot trial requires exact ordered application,
the same raw session/leader/global tracker/owner target after the final fault,
and coverage/I/O feedback. The pilot has its own denominator and cannot fill
the archived pre-I/O stage retroactively. No pilot is started solely from a
static call path; the two healthy raw traces must first establish the window.

## Calibrated healthy and one-fault pilot results

The first healthy calibration used agent SHA-256 `a781233f…` and passed the
original JUnit, but the adapter mislabeled six early unbound server handshakes
and 19 unrelated clients from test cleanup as binding errors. Those 25 events
occurred outside the selected upgraded-session/target window. The raw run,
agent JAR and receipt are preserved in the health archive; the adapter now
records those observations as `UNBOUND_IO` and keeps actual identity failures
as errors.

With agent SHA-256
`9e2ad5f3cdfd8ba45990a9802c351180d72afffac5320597714ab1208bd5f32f`,
two independent no-fault five-peer JUnits passed in 11.393 and 4.589 seconds.
Each had one selected global target guard with `present-open`, two ignored
local-tracker fallback guards, zero binding errors, and a distinct raw upgraded
session ID. They shared 35 actor-bound pre-target I/O occurrences. The
[healthy raw archive](evidence/zk03-upgrade-health-evidence.tar.gz) has SHA-256
`edf085483d38a05fd8ff4634af382f9cee3d90cf8f7db64731767f6f18a54347`.

The separate ten-plan single-`IOException` pilot injected **10/10** exact
actor-bound occurrences and retained the same raw-session/leader/global
target after the fault in **3/10** runs. The three retained plans faulted the
initial client's first or second socket read, or the reconnected client's
first socket write. No selected target `SessionExpiredException` occurred.
Independent reaggregation against both healthy coverage maps found **zero**
new instrumented production source lines, but **three** new target-window I/O
families. The pilot consumed **44.738 seconds** of original-JUnit JVM time.
Its [raw archive](evidence/zk03-upgrade-pilot-raw.tar.gz) has SHA-256
`815a5741d6b9e2b28d7d1ab0cd12564cb72de4dfab813e7a7746ba6d76148141`.
The checkpoint's first-row coverage novelty was initially measured against an
empty set; the [independent pilot audit](evidence/pilot-feedback-audit.json)
recomputes all novelty against the two healthy baselines. Only those corrected
figures are reported here.

Each retained first fault exposed another real client connection generation
(`channel:2`) before the selected global guard. The next stage mutates only
these observed postfault I/O points, with an independent denominator and no
replay of the pilot's completed plans.

## Observed recovery-I/O children

`prepare_recovery_children.py` enumerated 13 unique two-fault plans from the
three target-retaining pilot traces. The second selector in each plan is an
actor-bound `channel:2` I/O event actually observed after the parent's first
fault and before its selected global guard; each selector still carries the
same logical upgraded-session tag. The original five-peer JUnit was restarted
for every plan. The [independent child audit](evidence/child-independent-audit.json)
rechecked the ordered `FAULT_MATCHED` and `FAULT_APPLIED` events, raw-session
owner receipt and post-final-fault target in all trials.

All **13/13** plans applied both faults exactly; **7/13** retained the selected
target and none triggered its `SessionExpiredException`. The stage consumed
**78.366 seconds** of original-JUnit JVM time and added one instrumented
production source line plus three target-window I/O families relative to the
two healthy seeds and the retained pilot traces. The
[child raw archive](evidence/zk03-upgrade-recovery-children-raw.tar.gz) has
SHA-256 `1df48ccb56ec058b79f31dc42405cdd9ddb5bd57b263942f3d29b49a85d8f848`.
These are separate 13-trial results; they do not change either older
`QuorumTest` denominator.

## Deeper mutation campaign

The seven retained two-fault traces exposed further real connection
generations (`channel:3`) before the target. `deep_campaign.py` starts from
those raw traces and adds one observed I/O exception at a time, only after
the prior sequence's final fault and before the same-session target guard.
For each candidate, it stores the source parent, exact observed event index,
ordered plan and actor/resource occurrence. Its queue favors new I/O families,
new code coverage in selected production methods, and useful fault depths;
all selected trials still require raw full-occurrence injection and the same
raw-session/leader/owner target after the last fault. The fixed limits are
**80 effective trials for this SessionUpgrade seed in total**, at most eight
faults per sequence, and 256 selected depth-three-or-greater plans. Pilot and
child results count toward this seed's 80 only; older `QuorumTest` and MultiOp
results remain separate.

The node1 runner uses the same startup lock, Java and disk gate, original test
classes, fixed agent SHA, and slot 15 ports as the pilot. It writes an atomic
checkpoint before and after every JUnit. The supervisor resumes only at a
clean 30-minute wall-limit boundary after `audit_deep.py` rechecks parent
provenance, raw hashes, every fault, target identity, coverage and I/O
feedback. A selected target exception or timeout pauses for source and replay
review; an incomplete run is never counted or silently retried. The terminal
result follows.

## Terminal result and audit

The depth campaign stopped at `effective_budget_80_reached` after **131**
selected original-JUnit trials, before its 256-trial cap. **129/131** applied
every planned exception in order at the exact observed actor-bound I/O
occurrence. **70/131** reached the same raw-session, leader, global-tracker,
and owner target after the final fault. The two non-strict trials are retained
in the selected denominator and contribute neither strict injection nor
target retention. Across this independent original JUnit seed, the pilot,
two-fault child, and depth stages contributed **3 + 7 + 70 = 80/80** effective
trials. None produced the selected `SessionTrackerImpl.setOwner`
`SessionExpiredException`, so the bug mark is `none`.

The depth stage used **1,500.529 seconds** of original-JUnit JVM time and
exposed **12** additional target-window I/O families, including later client
connection generations, beyond the pilot and child feedback. It added **zero**
new instrumented production source lines beyond those earlier stages; the
child stage had added one. The three faulted stages together used **1,623.633
seconds** of JVM time. The two no-fault calibrations consumed another 15.982
seconds and remain outside the fault-trial denominator.

The [independent depth audit](evidence/deep-independent-audit.json) recomputed
all 131 ordered fault applications, parent observed-I/O provenance, raw
target identities, production line feedback, and I/O family feedback from the
[raw archive](evidence/zk03-upgrade-deep-raw.tar.gz). The archive contains 805
entries and has SHA-256
`ee783ec141d1c2b6ebf7a40e12999500682004a4a5cc1cc5c85cd5062d7cd139`;
the [archive receipt](evidence/deep-archive-receipt.json) records the terminal
checkpoint hash. Both files and the audit were copied from node1 and checked
against per-file SHA-256 values on both nodes.

The initial supervisor waited after the worker exited because `tmux`
interpreted the worker session name as a prefix of the supervisor session.
The supervisor now requires an exact session name. It then ran the independent
audit and archived the already-terminal checkpoint; no JUnit trial was
repeated. The fixed agent, original test method, and raw trial receipts are
unchanged. This outcome meets the defined effective-trial budget for this
check, within the observed actor-bound `IOException` fault model. It does not
establish that every distributed schedule or unbound startup I/O was tested.
