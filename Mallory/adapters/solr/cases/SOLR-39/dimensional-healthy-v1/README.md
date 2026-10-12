# SOLR-39 alternate healthy workload

The original Solr 8.11.4 `DimensionalRoutedAliasUpdateProcessorTest#testTimeCat`
starts a four-server `MiniSolrCloudCluster` and exercises a routed alias with
both time and category dimensions. This one-run package checks whether that
existing JUnit passes fault-free while reaching the exact SOLR-39 target.
It does not inject faults or count as a completed fuzz campaign.

The test source, agent, and adapter bytes are pinned in `run.py`. On node1:

```sh
python3 Mallory/adapters/solr/cases/SOLR-39/dimensional-healthy-v1/run.py --preflight-only
python3 Mallory/adapters/solr/cases/SOLR-39/dimensional-healthy-v1/run.py
```

Output is `data/mallory/calibration_solr39_dimensional_healthy_v1_node1/SOLR-39`.
The original Category selector already failed its own document-count assertion
in a fault-free run, so that result is not used as a healthy seed.

The one node1 run completed in 14.041 seconds with `MALLORY_TEST_RESULT`
reporting one test and one failure. It recorded zero exact SOLR-39 target
checks. The original test failed with `Expected no errors` after an ADD error
`java.lang.String cannot be cast to java.util.Date`. No fault was injected.
Thus this selector is also unsuitable as a healthy seed in the observed run.
The raw `pilot-result.json` was copied from node1 into the local output tree;
both copies have SHA-256
`c3e281471e4b5408fdbad8ba830a00882c2037f7f57d60895f0ce9ce07783b88`.
