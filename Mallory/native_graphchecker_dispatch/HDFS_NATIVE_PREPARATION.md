# Original GraphChecker HDFS preparation

`hdfs_native_adapter.py` turns a pinned HDFS inventory row into a native
GraphChecker campaign. Its request binds the target THROW, one compiled BRANCH
guard, and an unchanged upstream JUnit selector. The original Soot static scope
discovers typed I/O doors; the request and profile contain no door list.

The adapter runs, in order: original static ScopePlanner; source-built
`REGION_STATE` weave with the static fault manifest; the selected unchanged
JUnit with an empty fault plan and isolated data, temporary, and log directories;
original target occurrence Resolver at the exact guard; original Recorder and
Scheduler; and native campaign config validation. The THROW site and exception
remain a separate oracle from the guard. Each command, receipt, and output is
written under a new output root. A failed gate leaves its evidence in place.

```bash
export MALLORY_NATIVE_ENGINE_ROOT=/absolute/pinned/engine-source
python3 -m Mallory.native_graphchecker_dispatch.hdfs_native_adapter request \
  --inventory /absolute/pinned/inventory.json --case-id HDFS-32 \
  --out /absolute/pinned/HDFS-32-request.json
python3 -m Mallory.native_graphchecker_dispatch.hdfs_native_adapter prepare \
  --request /absolute/pinned/HDFS-32-request.json \
  --profile /absolute/pinned/profile.json \
  --out /absolute/new/HDFS-32-preparation
```

`profile.json` pins the original HDFS source revision, compiled class tree,
source-built engine receipt, helper, communication map, ordered classpaths,
classpath content hashes, Java binary, and bounded resource settings. The
adapter verifies these pins before running. Keep the profile free of case IDs,
JUnit selectors, target sites, and I/O door lists.

For an alternate unchanged JUnit, supply
`--alternate-junit-attestation /absolute/attestation.json` when creating the
request. The official attestation must bind the inventory selector to the
executed upstream source/class bytes, successful healthy JUnit, exact guard
Resolver receipt, and original trace. The HDFS-30 frozen attestation is an
example. This does not rewrite the inventory's recorded selector.

If an inventory row has several guards on different source lines, the request
defaults to the first mapping; `--selected-check-mapping` accepts another
mapping from that same row. Healthy execution must reach the selected Soot
guard. Several inventory branch ordinals on one source line remain ambiguous
without a finer source-to-Soot mapping; the adapter fails closed for those
rows. A new preparation root is required for each guard attempt.

Use `verify-existing` with `--static-root` and `--healthy-root` for a read-only
audit of a frozen preparation. HDFS-29 and HDFS-30 have been checked this way;
their active or completed fault campaigns were not replayed.
