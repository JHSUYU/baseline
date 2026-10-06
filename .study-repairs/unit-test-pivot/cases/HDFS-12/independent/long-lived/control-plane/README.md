# HDFS-12 long-lived-client control-plane supplement

This supplement runs the unchanged Hadoop 3.4.3 embedded-cluster JUnit
`TestEncryptedTransfer#testLongLivedClient[0]`. The test shortens the block
token key update interval and token lifetime to two seconds, clears the
NameNode's keys, reads/checksums a file, sleeps 15 seconds, then reads and
checksums it again. The released production check in
`BlockTokenSecretManager.retrievePassword` looks up the block token's key ID
in `allKeys`; an absent key throws the selected `InvalidToken`.

The case-local ASM overlay retains the HDFS-12 target and SASL socket-read
hooks and adds two control-plane I/O hooks: the DataNode heartbeat RPC and
the received active-NameNode key-update command. The original instrumented
healthy JUnit passed in 30.538 seconds, reached the selected lookup four
times with two distinct key IDs and no missing key, and observed seven
heartbeats and three key-update commands. The two independent one-fault
calibrations each matched once, left two target checks after the fault, and
passed the original JUnit: heartbeat ordinal four (33.119 seconds) and
key-update ordinal two (32.574 seconds). Neither threw the selected exception.
The three original JUnit traces, logs, coverage lists, and calibration plans
are in `calibration-evidence.tar.gz`; its SHA-256 is in
`calibration-evidence-index.json`.

`campaign.py` reuses the graph-independent coverage/I/O queue and exact
runtime-identity evaluator in the adjacent long-lived campaign. It seeds
the queue with all healthy observed I/O before the final target check,
prioritizes key-delivery I/O, then mutates sequences using production JaCoCo
coverage and newly observed I/O. A trial contributes feedback only if every
planned exception matches/applies in order and the same target check runs
after the last fault. The two calibration trials are counted as completed
sequences, so the campaign does not replay them. Budget: 80 trials, at most
eight ordered exceptions, conditionally 128/ten for late valid novelty.

The node2 tmux session is `hdfs12-control-campaign`. Its atomic checkpoint,
per-trial ledger and source evidence live under this directory. The node0
`hdfs12-control-sync` tmux session mirrors completed trial artifacts every
30 seconds and updates the 102-case table; an incomplete active sequence
remains in the node2 checkpoint for retry. A selected target throw is only
a replay/source-review candidate. Neither the older ordinary-read campaign
nor the SASL-only long-lived campaign is counted in this control-plane
campaign's trial total.
