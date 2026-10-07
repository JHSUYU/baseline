# HDFS-43 actor-aware original-JUnit replacement

## Evidence decision

The earlier 80 main and 128 supplementary trials remain archived under
`../independent/`. Their `FAULT_APPLIED` records contain only a normalized
thread name and a global `Client.getRpcResponse` ordinal. Their target check
contains file path and lengths but no block ID or request key. A later target
check cannot be tied to a particular client RPC or DataNode from those fields.
Historical `78/80` injection and `49/80` postfault-target counts therefore do
not qualify for this replacement.

The released Hadoop 3.4.3 source at `FSDirTruncateOp.java:113-117` compares a
second requested truncate length with the length already under recovery. The
unchanged `TestFileTruncate#testTruncateTwiceTogether` intentionally requests a
different length and expects `AlreadyBeingCreatedException`; that exact throw
is the healthy behavior, not a new bug.

## V2 identity and scope

The original MiniDFSCluster JUnit still performs all its original operations
and assertions. Case-local source overrides add only tracing and an ordered
exception gate:

- `Client.getRpcResponse` after request send records client ID, call ID,
  destination, and a semantic context supplied by the truncate or DataNode
  block-report translator. The fixture records the actual NameNode RPC port;
  only I/O whose physical destination port matches it can receive the `nn0`
  selector and qualify as a strict fault.
- The fixture maps `MiniDFSCluster.getDataNodes()` indices to physical UUIDs.
  A block-report selector includes the DN role, UUID in the event, and block ID.
- `FSDirTruncateOp.truncate` records path, last block ID, truncate block ID,
  both lengths, branch outcome, phase, and server-side client ID/call ID.
- The original JUnit has phase markers before the first and second truncate.
  Target eligibility requires the same file/block after the last applied
  fault, in the second-truncate phase. A second-truncate RPC requires the exact
  client/server request key; a prior truncate is recorded as the same-file
  predecessor; a DataNode block report requires the same block and UUID-to-role
  mapping. Ambiguous I/O is observed but not selected.

JaCoCo feedback is exported only for classes analyzed from the released HDFS,
HDFS client, and Hadoop common JARs plus the four production overrides. Probe
and JUnit classes are excluded. `METHOD` and `PROBE` are exact identities;
`BRANCH_UNIT` records covered branch counts per source line and does not label
which edge was taken. The target branch outcome is logged explicitly.

The new campaign has its own checkpoint and atomic per-trial result. It starts
at 80 attempts with at most 8 ordered faults; production coverage or a stable
I/O-family gain in chronological trials 73-80 extends it to 128 attempts and
10 faults. The previous trials are excluded from both the budget and coverage
union. An exact target outcome outside the original expected exception stops
the campaign for same-selector replay and source review.

## Setup status

The six released source files were copied into this case and match the clean
Hadoop 3.4.3 checkout. The V2 source overrides compiled with Java 8. The
synthetic, cluster-free `offline_smoke.py` passed its ordered selector and JSON
trace checks. Coverage exporter compiled. The original cluster JUnit healthy
calibration and fault campaign wait for the node2 resource gate; no V2 cluster
trial is claimed yet.
