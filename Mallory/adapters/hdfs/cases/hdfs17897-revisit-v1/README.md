# HDFS-17897 isolated revisit

Source: Hadoop 3.4.3 commit `9d50c6884666e794e45102260a4017bb31802e1b`.
All JUnit runs and modified bytecode live in this case directory. The shared
Mallory agent and adapter release JARs were read only.

## Mechanism-faithful known-bug control

`evidence/original` and `evidence/fixed` run the encrypted XOR-2-1 checksum
workload with actual NN key rotation and expiry on all three DNs. The original
class throws `PathIOException` after every DN rejects the cached key, and the
same client's retry fails. The patched class clears the cached key, retries,
and returns the healthy checksum. This is an already known bug control and does
not use Mallory's graph or injected exceptions.

## Mallory pilot with the original selected JUnit

`mallory-healthy` passed both `TestFileChecksum` variants, reached the exact
HDFS-54 check, and had a valid event-time graph with five eligible pre-target
doors. `mallory-full` completed four effective typed `IOException` trials;
three retained the target and none threw the selected `PathIOException`. One
NN location-read fault failed JUnit, but that failure was an injected generic
I/O error, not HDFS-17897. This JUnit does not enable encrypted transfer.

## Typed exception path diagnostic

`hadoop-worktree` adds only `TestStripedChecksumFaultPath`, an encrypted
XOR-2-1 workload whose healthy checksum succeeds. `typed-key-healthy` passed
and reached the target with an exact `InvalidEncryptionKeyException` door at
`connectToDN`. The automatic `typed-key-full` campaign completed ten trials
with no target exception.

The three-fault plan in `typed-key-targeted/graph-derived-plan.json` was
constructed from that healthy door event and applied to ordinals 1, 2, and 3.
Both original runs (`typed-key-targeted` and `typed-key-targeted-replay`)
recorded three applied exceptions in one `checksumBlockGroup` occurrence,
followed by the exact `PathIOException` throw at `checksumBlocks` line 631
and one JUnit error. This sequence was manually selected after the automatic
campaign; it is not an automatic scheduler discovery.

`hadoop-fixed-worktree` overlays the HDFS-17897 clear/retry source and classes.
The source insertion moves the corresponding door from line 686 to line 694.
With that mapped door, `typed-key-fixed-mapped/trials/r0001` applied all three
exceptions, logged the clear/retry branch, restored the healthy checksum, and
passed JUnit without a target throw. The class identity and site catalog were
verified. Earlier directories `typed-key-fixed-comparison` and
`typed-key-fixed-overlay` had a class or site mismatch and are excluded.

This typed exception differential diagnoses the missing catch; it does not
establish actual stale DN key state. The separate key-expiry control supplies
that evidence. Neither run is a new bug claim. `review-receipt.json` contains
the per-run hashes and exact artifact paths.
