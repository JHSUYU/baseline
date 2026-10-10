# SOLR-37 operand telemetry frame repair, healthy only

The previous `operand-telemetry-v1` healthy trial is invalid. Its JUnit failed
before reaching `DistributedZkUpdateProcessor.doDefensiveChecks@994`: the JVM
rejected the rewritten method with `VerifyError: Expecting a stackmap frame at
branch target 374`. The later `2 vs 4` replica mismatch and leaked threads
followed failed replica recovery. They are not evidence of a Solr bug.

The Mallory coverage transformer first adds conditional branches and computes
stack map frames. The v1 case adapter then inserted the exact operand hook but
used `COMPUTE_MAXS`, retaining stale frames. This v2 adapter recomputes frames
after rewriting `DistributedZkUpdateProcessor`; all other v46 hooks remain
unchanged. The offline unit test applies both transformations to the pinned
Solr class, verifies the result with ASM, and asks the JVM to load and inspect
the rewritten class. `mvn -q -o test` passes all three tests.

The existing cluster JUnit is still `ShardSplitTest#test`. A successful prior
healthy run of that same test reached the exact named @994 target. The new
package runs one fresh healthy trial under a new output root. The node0 lane
steward must issue a matching case-local GO receipt before a cluster JVM runs.

From the baseline root, static preflight:

```
python3 Mallory/adapters/solr/cases/SOLR-37/operand-telemetry-frames-node0-v2/run_campaign.py --mode healthy --preflight-only
```

Runtime admission requires JUnit 1/0/0, named exact target checks, and an
observed same-reader, same-collection watcher publication to the target read
with a time-respecting graph path and recorded range operands. A passing JUnit
alone does not authorize fault trials. A later injected exception must retain
the exact target and show a source-backed effect on the operand before a full
campaign is admitted. This package cannot run faults.
