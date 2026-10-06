# SOLR-07: independent recorder replay pending

The earlier 30 trials used GraphChecker-region-derived runtime selectors or frozen woven classes. Their full result is preserved in [legacy-graph-result.json](legacy-graph-result.json); those attempts are excluded from the graph-independent campaign. The original `AddReplicaTest#testAddMultipleReplicas` cluster JUnit will be rerun with a case-local recorder and production coverage feedback.
