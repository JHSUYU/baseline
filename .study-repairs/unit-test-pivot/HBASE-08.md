# HBASE-08: namespace check under original cluster test

The workload is the original HBase 2.6.6
`TestNamespaceAuditor.testTableOperations` JUnit method, which starts its
embedded HBase cluster. The healthy test reached the selected namespace
guard nine times, all on its nonfatal outcome.

The historical campaign ran five fault trials. Four matched and applied a
selected fault, and four retained the target after injection. One selector
did not match. Two distinct I/O points were tested: ZooKeeper child read
and a ZooKeeper write response. The v3 child-read trial gained 19 scoped
branch outcome pairs and 11 method entries; the v6 write-response trial
gained four branch pairs and one method entry against its own healthy run.
These scoped counts cannot be added across builds. No trial took the
selected fatal outcome, and no new bug was confirmed.

The campaign records 761.55 seconds elapsed. The exact trial plans,
checkpoints, and coverage summaries were retained in
[cases/HBASE-08/evidence/legacy-trials](cases/HBASE-08/evidence/legacy-trials);
the machine-readable verdict is [result.json](cases/HBASE-08/result.json).
The five historical trials leave the current 48-trial budget and further
relevant I/O families open.
