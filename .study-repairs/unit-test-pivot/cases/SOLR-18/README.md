# SOLR-18: aliases equality under ordered ZK faults

The selected check is `ZkStateReader.AliasesManager.setIfNewer` at original
Solr 8.11.4 source line 2347. For equal znode versions, it asserts that the
cached and incoming alias JSON are equal.

The first actor-bound campaign used the unchanged original
`AliasIntegrationTest#testProperties`. Its observed I/O plans exhausted after
845 attempts and 68 strict same-client, postfault target trials, short of its
80-effective budget. Its full original result is preserved verbatim in
[first-phase-result-frozen.json](actor-v2/alternate-junit/first-phase-result-frozen.json),
with the 845/68 checkpoint and raw audit linked there.

A separate original `AliasIntegrationTest#testDeleteAliasWithExistingCollectionName`
campaign calibrated a new first-`CreateAliasCmd` oracle on the same source
guard. One clean and two no-fault instrumented original JUnits passed and
showed 183 stable new same-actor I/O selectors. A five-trial pilot had three
strict effective trials; those five are excluded from the full denominator.
The [alternate campaign](actor-v2/alternate-junit/README.md) then completed
150 original JUnit fault attempts and **80 strict effective trials** under one
live `SolrZkClient` actor per run, after the final ordered fault. The bounded
80-effective budget finished; the conditional 128/10 extension did not
trigger because its last eight effective trials added no production method or
stable relevant I/O family.

All 80 effective original JUnits passed. All 86 selected equal-version JSON
checks were true, and the selected assertion never threw. No new bug is
confirmed. Compared with healthy controls, effective trials covered 186 new
production probes, 10 methods, and 186 lines. The plan cap allowed eight
faults; actual attempts reached depth three before budget completion, leaving
1,348 unique plans pending. This is a bounded reliability result, not an
exhaustive proof over fault schedules.

[Full checkpoint](actor-v2/alternate-junit/full-state.json),
[independent raw audit](actor-v2/alternate-junit/full-audit.json),
[independent TSV recount](actor-v2/alternate-junit/independent-recount.json),
and [terminal receipt](actor-v2/alternate-junit/terminal-receipt.json) retain the
separate denominators, source/JUnit hashes, target identity checks, coverage,
elapsed time, and 15 node2 SHA mirror receipts. Node0 keeps every trial's
event trace, JaCoCo, JUnit console and run receipt. Only SHA verified derived
coverage text from noncandidate trials 001–120 was offloaded to its complete
node2 copy, with a remote restore smoke and an audit that verifies the archive.
