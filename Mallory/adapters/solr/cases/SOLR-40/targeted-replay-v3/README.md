# SOLR-40 caller-side exception probe validation

The Solr 8.11.4 bytecode for `getAliasProps` calls
`RoutedAlias.newAliasMustExistException(String)` at bci 32, then has an
`ATHROW` at bci 35. The callee itself throws. The v2 probe watched that
unreachable caller `ATHROW` and missed two source-confirmed target exceptions
in the ten-run node3 replay.

`sites.json` now matches the callee at source line 133. The existing
`MalloryTransformer.instrumentCallThrow` records an exception crossing that
call. The call is the seventh invocation in this method, so the target is
`@133:callthrow:7`. This is confirmed by `javap -c -l -p` on the pinned
`solr-core-8.11.4.jar`; the runtime site catalog must also confirm it.

`probe_validation.py` runs one healthy JUnit and three independent exact
node3 ordinal-1 fault replays under
`data/mallory/solr40_callee_probe_v3_node0/SOLR-40/`. The plan comes from
v2 trial r0007 and is explicitly prior-witness-seeded, not Mallory automatic
discovery. It takes the Solr node0 and shared source locks before launching
JVMs. The original v2 and ten-run raw results are not rewritten.
