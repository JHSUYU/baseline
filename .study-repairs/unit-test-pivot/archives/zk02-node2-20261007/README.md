# ZK02 legacy trace archive, node2

`archive_verified.py` archives only the completed, historical GraphChecker
ZOOKEEPER-02 attempt traces under node2's
`/users/ZhenyuLi/zk02-unit/campaign/results/ZOOKEEPER-02/trials`.
The 128-trial historical campaign has already been excluded from the revised
graph-free baseline. Its existing 248-row `archive-manifest.jsonl` and pinned
SHA remain untouched.

For every remaining raw `runtime_trace.jsonl` or `schedule.jsonl`, the script
checks no process has the campaign directory open, compresses at low CPU/I/O
priority, compares the raw SHA-256 with the decompressed bytes, copies the
compressed file to `node1:/users/ZhenyuLi/zk02-archive-mirror-20261007`,
compares the two compressed SHA-256 values, and writes an individual JSON
receipt to both hosts. It removes that raw file only after all checks pass.
The script can resume from a partial run. At terminal state it requires 52
receipts, zero remaining raw files, writes a new manifest on both hosts, and
confirms the historical manifest SHA did not change. It does not access the
SOLR31, ZK13, or SOLR10 workspaces.
