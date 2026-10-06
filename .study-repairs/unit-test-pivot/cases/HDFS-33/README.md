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
