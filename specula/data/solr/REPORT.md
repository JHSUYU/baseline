# Solr: Specula ad hoc coordination results

One Specula run per check; model `claude-opus-5-5[1m]`. Effort `max` for runs before 2026-11-04 and `high` after (counted together, owner). Time is active time: quota sleeps are excluded (`tools/active_time.py`). Tokens and cost include usage overwritten by restarts (`tools/case_tally.py`).

## Summary

- Checks: 13; verdicts: NOT RUN (owner: no bug found) 1, REACHED_CONFIRMED 12.
- Total: 26h43m active, 728.8M tokens, $448.96.
- Verified bugs (real, severe, fail the ad hoc check): **0** (see `VERIFIED-BUGS.md`).

## Per check

| check | verdict | active time | tokens | cost | verified bugs |
| --- | --- | ---: | ---: | ---: | --- |
| solr-adhoc-05 | REACHED_CONFIRMED | 4h31m | 78.6M | $46.98 |  |
| solr-adhoc-07 | REACHED_CONFIRMED | 1h58m | 47.7M | $31.01 |  |
| solr-adhoc-09 | REACHED_CONFIRMED | 1h58m | 68.9M | $44.57 |  |
| solr-adhoc-10 | REACHED_CONFIRMED | 1h59m | 66.3M | $39.47 |  |
| solr-adhoc-13 | REACHED_CONFIRMED | 2h01m | 56.3M | $34.62 |  |
| solr-adhoc-14 | REACHED_CONFIRMED | 1h45m | 56.0M | $35.24 |  |
| solr-adhoc-19 | REACHED_CONFIRMED | 1h29m | 40.2M | $27.47 |  |
| solr-adhoc-21 | REACHED_CONFIRMED | 1h44m | 59.4M | $38.66 |  |
| solr-adhoc-31 | REACHED_CONFIRMED | 2h55m | 90.2M | $50.03 |  |
| solr-adhoc-38 | REACHED_CONFIRMED | 2h12m | 56.0M | $33.62 |  |
| solr-adhoc-39 | REACHED_CONFIRMED | 1h24m | 46.3M | $30.12 |  |
| solr-adhoc-40 | REACHED_CONFIRMED | 2h43m | 62.9M | $37.17 |  |
| solr-adhoc-22 | NOT RUN (PORT_BLOCKED; owner: no bug found) | 0 | 0 | $0 | |

## Caveats

- solr-adhoc-22 was not run (workload PORT_BLOCKED); counted as no bug found (owner).
- 2 of the Solr runs used Claude Code CLI 2.1.318, the rest 2.1.312.

Verification: `../batches/VERIFY-*.md` (independent reviewer against the source; the operator re-read the decisive code). No tests were rerun for verification.
