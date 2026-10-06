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
automatic bug verdict. The campaign is running; no final negative result is
claimed yet.
