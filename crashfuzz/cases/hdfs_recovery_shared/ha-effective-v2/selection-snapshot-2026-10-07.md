# HA campaign selection snapshot (read only)

At the node1 checkpoint after 41 completed trials, the new 3NN/3DN original
JUnit campaign had 13 fully applied sequences and 9/13/13 effective trials
for HDFS-28/29/30. The independently audited 37-trial prefix had zero raw
receipt errors. This note analyzes selection yield only; it does not change
the running scheduler or its checkpoint.

| Last selected I/O family | Attempts | Fully applied | HDFS-28 effective | HDFS-29 effective |
| --- | ---: | ---: | ---: | ---: |
| NameNode/DataNode RPC | 21 | 10 | 8 | 10 |
| DataNode replica-check file I/O | 20 | 3 | 1 | 3 |

The current scheduler balances exception types before using previous
target-retention feedback. That gave 20 of the first 41 selections to the
replica-check file family, whose observed strict/target-retaining yield is
lower in this prefix. Its healthy traces still establish this as a real
pre-target family, so later exploration should retain a small file-I/O share.
If the campaign stops at the 320-attempt cap before all three checks reach
their 80-effective goals, inspect the then-current raw distribution and make
an audited checkpoint-boundary migration: retain every completed trial and
queued selector, raise only the attempt cap as needed, and rank observed RPC
selectors ahead of repeatedly target-losing file selectors while reserving
periodic file exploration. A cap stop alone is inconclusive, not completion.
