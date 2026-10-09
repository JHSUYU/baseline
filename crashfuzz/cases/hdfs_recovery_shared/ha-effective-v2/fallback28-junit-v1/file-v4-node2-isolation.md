# HDFS-28 alternate FILE V4 node2 handoff

The alternate original JUnit is
`TestPipelinesFailover#testLeaseRecoveryAfterFailover`. Its IPC V3
checkpoint naturally stopped at 214 selected attempts, 41 strict postfault
HDFS-28 checks, no active trial, no queued plan, and 111 seen selector IDs.
That frozen node1 checkpoint has SHA-256
`782f1f1eb52c9412e95d2c71765d94354e98fe829af4ad5c608d6d0a7`.
The node1 alternate controller remains stopped; node2 is authoritative for
the FILE V4 continuation. The shared HA JUnit remains a separate live
campaign on node1 and retains its own denominator and checkpoint.

The entire frozen alternate directory was streamed from node1 to the same
absolute path on node2. Node2 independently hashed and compared all 2,437
copied files (1,882,299,858 bytes) against
`../file-v4-transfer-inventory.json`, whose SHA-256 is
`cd4c6097ab6fb1803ceec371563d140a5823cb601dc407594f10c071066cc27b`.
No old trial was run during this transfer. Node2 also has the matching
released Hadoop tests JAR and test-resource hashes from the two healthy
manifests, and exact `campaign.py`/`run_original.py` source hashes required
by `campaign_v1.py`. The HA topology uses the original JUnit's
`MiniDFSCluster.Builder` and default port-zero `NNConf` entries. Each run
has its own scratch directory. Node2 uses its own instance of the shared
`jvm-start.lock` with at most four existing Java processes and at least
10 GiB free before each launch.

The node2 preview matched the frozen node1 preview byte-for-byte (SHA-256
`503e3ab44684bed74a7207b7f8e0f67d75195b887105c7bcf33a3a11de5b9a43`):
72 unseen same-owner/recovery-root, target-before FILE singleton plans,
including 24 local and 48 remote replica plans. The handoff independently
audited all 214 old attempts with zero errors and atomically appended those
72 IDs, leaving every old completed record, queue, seen prefix, coverage,
and stable I/O set unchanged. No new ID overlaps the old seen ledger. Its
intent and receipt have identical SHA-256
`99a78eb7111c9dc3950287f63b536a55d9b89d46d7ea983001e40eccad84b12b`;
the old and new checkpoint hashes, added selector list, and 320-to-512 cap
change are in that receipt. The resumed controller runs in node2 tmux
`hdfs28_file_v4_node2`. An unmatched plan may receive bounded retries under
the preexisting policy; those are separate attempts with the same plan ID,
not a new selector.
