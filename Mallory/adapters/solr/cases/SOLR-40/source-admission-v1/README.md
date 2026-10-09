# SOLR-40 source-only admission gap

No healthy or fault JVM was run for this review. The pinned Solr 8.11.4
checkout is `e27f44e3d78dfcec230c97e0a1240e3751daeff9`.

The selected check is
`RoutedAliasUpdateProcessor#getAliasProps(...)@132:branch:1`; line 133
throws if the cached alias properties map is empty. The target source
SHA-256 is `6ed4337435f68d00ba85d7b05eeb324cea9a14298c34cabd137756d682f24590`.
The existing four-node `TimeRoutedAliasUpdateProcessorTest#test` creates a
time-routed alias and indexes a document through it (`TimeRoutedAliasUpdateProcessorTest.java:87-95,110-139`).
Its source SHA-256 is
`727cc38dd0fd0d42e641724b08d96b00e0e9d8ab492d23cbc572284824079d37`.
The older healthy calibration failed at ConfigSet creation before this target;
the staged ConfigSet setup overlay has not been executed for this case.

At the selected method, `getAliasProps` reads
`zkController.getZkStateReader().getAliases()` and inspects the returned
cached map (`RoutedAliasUpdateProcessor.java:129-135`). It performs no typed
I/O and has no local retry. Its caller catches `Exception` and wraps it in a
`SolrException` (`119-124`), which does not retain this invocation after a
failed read. `ZkStateReader$AliasesManager.process` does catch
`ConnectionLossException` from `SolrZkClient.getData` in an asynchronous
watcher callback (`ZkStateReader.java:2312,2317-2319`), so a stale cached
alias is a source-level possibility. That callback has a different execution
context and no demonstrated unique request/task token into the selected
`getAliasProps` occurrence. Equality of the alias name or event timing would
not supply the missing edge.

This review found no caught or retrying **typed pretarget I/O on a traceable
path** that can be admitted for the selected check. SOLR-40 remains a
source/fault-model gap. A future healthy run or new watcher-to-request
version edge could be assessed separately; this review stages no pilot or
full campaign and makes no bug claim.
