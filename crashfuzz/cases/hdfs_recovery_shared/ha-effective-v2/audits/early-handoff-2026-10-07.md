# HA effective campaign: audited scheduler handoff

On 2026-10-07 at 13:05 UTC, node1's original `TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization` campaign changed scheduling policy at a reserved, unstarted trial boundary. The old Python controller was waiting on the shared `jvm-start.lock`; trial 137 had a fault plan but no driver, JUnit, trace, manifest, or Java child. No running JUnit was signalled.

The reason was measured from the **last 12 completed trials**: all 12 final faults were `HDFS_FILE`, and only 2 trials satisfied strict ordered injection plus a same-actor postfault target check. The old campaign had completed 136 trials; its independent raw auditor found 0 inconsistencies and 0 target exception candidates. Effective counts were HDFS-28 26, HDFS-29 47, HDFS-30 47. All counts are for this HA original JUnit only; earlier `TestBlockRecovery2` attempts stay separate.

| Invariant | Boundary record |
| --- | --- |
| Original `campaign.py` SHA-256 | `824df96b2fbbcfeb2d29d444443a837f414d183f90e28fdf2789c8a07a40b93b` |
| Old checkpoint and byte-for-byte backup SHA-256 | `4f543a865fbca3da3f992384967b09185fce0b94e713dca41cfa2b15b13f8f9f` |
| Reserved trial 137 plan ID / SHA-256 | `43a15f6f755172b608a97cc3` / `acdbaf0756a7972eb779e1ec4e3573691162986b50e889e2d026035240259121` |
| Independent pre-stop raw audit SHA-256 | `51676e691c878137e30a98ca630ac29928ab96fb21ef7f5c340d418c1143af9c` |
| Successor `successor.py` SHA-256 | `a431bb25ec9476b8d60a3e9cff4c01fad3c7b4ef93f91d96330882bf103d3130` |
| New scheduler checkpoint SHA-256 | `83dbf73245f0003914e1632f50b9608228084a186f7bc26ea5426ed54148cc12` |
| Completed / queue / seen | `136→136` / `276→276` / `336→336` |
| Active plan | Trial 137 plan ID unchanged |

The local copies [early-quiesce-receipt.json](early-quiesce-receipt.json), [successor-handoff-receipt.json](successor-handoff-receipt.json), and [handoff-raw-audit.json](handoff-raw-audit.json) were pulled from node1. A separate cross-check compared their SHA fields, the case-local old/new sources, all list counts, the active ID, and the raw audit's effective counts. The original checkpoint backup and every trial directory remain on node1. The successor's policy is four RPC slots to one file-I/O slot, with an HDFS-28 focus after peers 29/30 reach 80; it first resumes the already reserved trial 137.
