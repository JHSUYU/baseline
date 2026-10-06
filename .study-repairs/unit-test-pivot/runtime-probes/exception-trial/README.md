# Exception trial selector probe

This small artifact preserves the historical ordered-fault controller change
and its selector regression fixture. `controller.patch` adds the controller
and trace events to the original runtime. `identity-fix.patch` records the
later full occurrence-address fix for an earlier controller revision. The
current external baseline runtime already contains that fix.
The patches are source references; current case runs use pinned external
runtime JARs and do not load this directory.

Run the fixture against an existing runtime JAR that contains the controller:

```sh
python3 run_fixture.py \
  --jar /path/to/GraphChecker-1.0-SNAPSHOT-jar-with-dependencies.jar \
  --out /tmp/baseline-exception-trial-probe
```

The probe compiles `fixtures/*.java` into the requested scratch directory,
then runs the same JUnit method without a fault, with one and two ordered
faults, with a different request context, with a noncanonical address, and
with an unmatched selector. It checks applied-event order, target-after-fault
reporting, exact address matching, and ordinary trace parsing. The fixture
models an I/O door; it does not establish coverage or correctness for a
distributed-system case.

On 2026-10-06, `git apply --check` accepted `controller.patch` against the
clean study checkout. The probe passed against the existing
`GraphChecker-unit-baseline` runtime JAR. Its output was:

```text
PASS trace parser: 2 methods, 12 execution rows
PASS same JUnit method: healthy, one fault, ordered two faults, distinct context, same-ID address alias rejected, unmatched
```
