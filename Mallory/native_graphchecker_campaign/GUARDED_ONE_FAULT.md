# Guarded one-fault continuation

`guarded_one_fault.py` runs the existing native original-GraphChecker campaign
with an **absolute completed-fault-trial stop**. It chooses no fault site and
does not change the original JUnit or GraphChecker feedback. A new attempt ID
starts at the checkpoint's accepted fault count `N` and stops after `N+1`.
Retrying the same attempt ID retains that bound, even if the wrapper was
interrupted after the child accepted the trial.

The wrapper requires a private, same-UID mount namespace in which the entire
PG0 input tree is read-only, including nested mounts. Its output, JUnit work
root, and raw artifact root must be separate dedicated host-local filesystems
outside PG0. It refuses a writable PG0 tree or a root/NFS output. The caller
must precreate those local roots and run a no-workload mount smoke first.
The wrapper monitors raw bytes **added by this attempt**, total output bytes,
their free-space floors, memory, and wall time. A cap or floor breach stops
the child process group; the campaign checkpoint remains available for the
same attempt ID to resume. The monitor polls at most every three seconds, so
the capacity reservation must include growth during one poll and termination.

The campaign source containing `--stop-after-fault-trials` must be pinned by
SHA-256. Frozen older campaign sources without this flag cannot use the
wrapper; stage a versioned source snapshot and validate its original engine,
weave receipt, config, and checkpoint compatibility before a JUnit launch.
The wrapper verifies the config and campaign source hashes on every call.

Example namespace entry (paths and capacity values must come from a reviewed
case-specific recipe):

```bash
unshare -U -c --keep-caps -m --fork --propagation private \
  sh -c 'mount --bind "$1" "$1" && mount -o remount,bind,ro "$1" && shift && exec "$@"' sh \
  "$PG0_INPUT" python3 -m Mallory.native_graphchecker_campaign.guarded_one_fault \
  --pg0 "$PG0_INPUT" --config "$PINNED_CONFIG" --output "$LOCAL_OUTPUT" \
  --raw-root "$LOCAL_RAW_ROOT" --attempt-id "$ATTEMPT_ID" \
  --config-sha256 "$CONFIG_SHA256" --campaign-source-sha256 "$SOURCE_SHA256" \
  --max-raw-bytes "$RAW_CAP" --max-output-bytes "$OUTPUT_CAP" \
  --min-raw-available-bytes "$RAW_FREE_FLOOR" \
  --min-output-available-bytes "$OUTPUT_FREE_FLOOR" \
  --min-memory-available-bytes "$MEMORY_FLOOR" \
  --max-wall-seconds "$WALL_LIMIT" --poll-seconds 1
```

This code is an opt-in capacity wrapper. A live campaign additionally needs
source/classpath/JUnit pin verification, a free node slot, and a fresh local
capacity preflight. No existing frozen campaign pin is rewritten by it.
