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
sequences, so the campaign does not replay them. The budget was extended
from 80 trials/eight faults to 128 trials/ten faults after valid novelty.

The node2 tmux session `hdfs12-control-campaign` completed all 128 trials;
node0 `hdfs12-control-sync` mirrored the raw evidence. Independent raw-event
audit found 114 exact ordered injections, 86 target checks after the final
fault, and 86 of those using a rotated key ID. No selected null-key
`InvalidToken` throw occurred. Its atomic checkpoint, per-trial ledger, and
source evidence are under this directory; the case-level audit and SHA-256
archive are documented in `../../audit-all.json` and the case README. Neither
the ordinary-read campaign nor the SASL-only long-lived campaign is counted
in this control-plane campaign's 128 trials.
