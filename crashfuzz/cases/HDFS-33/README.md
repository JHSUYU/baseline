# HDFS-33: block-pool metadata during volume hot swap

The selected Hadoop 3.4.3 assertion is in
`DataStorage.VolumeBuilder.build`. For every block-pool ID prepared for the
new volume, it requires an entry in `DataStorage.bpStorageMap` before adding
that pool's storage directories. `prepareVolume` obtains namespace info,
calls `getBlockPoolSliceStorage(nsInfo)` (which creates the map entry if
missing), and later `build` consumes the prepared IDs. A concurrent
`removeBlockPoolStorage` between those steps is a relevant state change to
examine, but this source review does not claim it occurs in a test.

The original `TestDataNodeHotSwapVolumes#testAddOneNewVolume` starts an
embedded one-NameNode, one-DataNode cluster, adds a volume through the
DataNode reconfiguration path, writes blocks, and checks block reports across
three volumes. It is a concrete workload for healthy calibration of the
selected `build` loop. Case-local instrumentation must verify that the exact
assertion executes, record the block-pool ID and DataNode identity, and
identify observed I/O before any fault trial counts.

The unchanged released `TestDataNodeHotSwapVolumes#testAddOneNewVolume`
passed without hooks in 21.322 seconds. A separate run with a case-local
offline ASM overlay and JaCoCo passed in 24.574 seconds; it observed exactly
one execution of the line-259 assertion with a non-null block-pool storage
object, and zero target throws. The overlay records the builder identity and
block-pool ID at the exact guard. It also records actual Hadoop IPC response
reads; the first healthy target has six such reads before it.

`independent/campaign.py` runs the same original JUnit, mutates observed IPC
fault selectors using production JaCoCo probe gain and new I/O families, and
persists a checkpoint plus one ledger row per trial. Faults are
`IOException`, `SocketTimeoutException`, or `EOFException` at a matched
response read. A trial contributes feedback only when every fault matches in
order and the same selected assertion executes after the last fault. The
selected assertion throw is a replay and source-review candidate, not an
automatic bug verdict.

The campaign stopped on the **80 strict target-retaining trial** budget after
102 attempts (100 strict matches). All 80 target-retaining original JUnit
runs passed; none threw the selected assertion. The case gained 262 HDFS/IPC
production JaCoCo probes. Ten valid sequences used one fault and 70 used two.
All 18 strictly applied three-fault sequences removed the selected target, so
they were recorded as attempts without contributing target feedback. The last
eight valid trials added no production probe or stable I/O family; the
conditional larger budget was not taken. Healthy plus fault-run elapsed time
was 2,394.916 seconds. This is a bounded negative finding for this original
JUnit and its observed IPC response fault sites.

`independent/audit_campaign.py` reclassified every completed plan directly
from its saved original JUnit trace, manifest and exact target identity; the
102 checks matched the checkpoint. The raw trace, JUnit log, JaCoCo exec,
plan, healthy seed and audit are in `HDFS-33-independent-evidence.tar.gz`
(SHA-256 `962ca90b4a4418d56ff62d26cf39a2bd21facf9ae6a35832f02195b2f3566b75`).
`independent-archive-manifest.json` gives its size and file count.

The source relation behind the guard is narrow. `prepareVolume` obtains each
block-pool storage through `getBlockPoolSliceStorage`, which creates the map
entry if needed, before adding the same pool ID to the builder. `build` reads
that map under the storage lock. The only map removal is on block-pool shutdown
after the final BP actor exits. The one-NameNode, one-DataNode original test
does not request such a shutdown, although an IPC fault could affect actor
lifetime indirectly. The fault scope here was observed `Client.getRpcResponse`
events; checked file-I/O failures during volume preparation normally abort
before this builder guard. No new bug is claimed.
