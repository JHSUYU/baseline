# Native GraphChecker row hook bridge (opt-in prototype)

This isolated module calls the original GraphChecker `RowRuntime` and
`SessionPublisher` from commit `c4a90033c654737206466ed36ce837c5b3c12457`.
At startup it verifies the loaded GraphChecker jar SHA-256. It creates the
original `sessions/<sessionId>/` files, and its test reads them through the
original `SessionReader`. It is not wired into any active Mallory campaign.

The bridge's methods define the minimum data that an eventual opt-in weaver
must pass at the event itself:

| Event | Required evidence |
| --- | --- |
| Activation | Original `OccurrenceAddress`, thread/claimed-work key and exact message producer endpoint when anchored |
| Decision/target | Exact site, branch ordinal/outcome/fatal polarity, and captured expression DAG |
| State write | Original `LocationId`, actual write version, event sequence, value expression, site execution index |
| State read | Same location, **observed** version, read symbol and concrete value, site execution index |
| Wire export/attach | Exact producer and consumer endpoints, payload expression, minted handoff symbol, correlation and pairing key |

The current Mallory JSON trace does not contain these expression DAGs or
exact Java field read versions. This bridge therefore refuses to infer them
from the trace. Passing only an opaque `locationVersion` or a boolean target
outcome is insufficient for native value-demand closure. Until the hooks
capture the evidence at runtime, the migration cannot claim complete READ,
WRITE, EXPORT, ATTACH or target-predicate causality.

`NativeRowHooks` is intentionally strict at its API boundary. A caller should
emit an original blocking `UNSTATED_VALUE` gap through `missingEvidence` if
the runtime hook cannot obtain a required value; a production weaver adapter
must catch any hook failure so it never changes application behavior. Neither
the existing `TrialGraph` nor the current fault controller is replaced here.

Run the focused round-trip test with `mvn -q test` from this directory.
