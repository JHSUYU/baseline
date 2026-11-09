# HBase: Specula ad hoc coordination results

One Specula run per check; model `claude-opus-5-5[1m]`. Effort `max` for runs before 2026-11-04 and `high` after (counted together, owner). Time is active time: quota sleeps are excluded (`tools/active_time.py`). Tokens and cost include usage overwritten by restarts (`tools/case_tally.py`).

## Summary

- Checks: 19; verdicts: REACHED_CONFIRMED 18, REACHED_UNCONFIRMED 1.
- Total: 70h57m active, 1756.6M tokens, $1385.45.
- Verified bugs (real, severe, fail the ad hoc check): **7** (see `VERIFIED-BUGS.md`).

## Per check

| check | verdict | active time | tokens | cost | verified bugs |
| --- | --- | ---: | ---: | ---: | --- |
| hbase-adhoc-04 | REACHED_CONFIRMED | 2h38m | 101.1M | $67.38 | MC-3 (B) |
| hbase-adhoc-07 | REACHED_CONFIRMED | 4h35m | 122.4M | $80.75 |  |
| hbase-adhoc-08 | REACHED_CONFIRMED | 3h10m | 137.0M | $88.01 | MC-3 (B), MC-1 (B) |
| hbase-adhoc-10 | REACHED_CONFIRMED | 5h20m | 119.1M | $93.01 |  |
| hbase-adhoc-11 | REACHED_CONFIRMED | 6h41m | 159.1M | $132.53 | MC-3 (A, =10/CR-1), MC-2 (B) |
| hbase-adhoc-12 | REACHED_CONFIRMED | 3h06m | 115.5M | $76.06 |  |
| hbase-adhoc-13 | REACHED_CONFIRMED | 2h23m | 89.7M | $56.46 |  |
| hbase-adhoc-14 | REACHED_CONFIRMED | 3h13m | 104.8M | $74.05 |  |
| hbase-adhoc-15 | REACHED_CONFIRMED | 2h49m | 109.6M | $81.69 |  |
| hbase-adhoc-19 | REACHED_CONFIRMED | 4h10m | 79.9M | $57.95 |  |
| hbase-adhoc-20 | REACHED_CONFIRMED | 3h01m | 78.1M | $63.50 |  |
| hbase-adhoc-21 | REACHED_CONFIRMED | 2h33m | 41.4M | $44.58 | MC-4 (B, =22/CR-1) |
| hbase-adhoc-22 | REACHED_CONFIRMED | 3h17m | 77.5M | $89.06 |  |
| hbase-adhoc-24 | REACHED_CONFIRMED | 2h59m | 48.4M | $53.52 |  |
| hbase-adhoc-28 | REACHED_UNCONFIRMED | 2h35m | 21.9M | $28.20 |  |
| hbase-adhoc-31 | REACHED_CONFIRMED | 4h21m | 99.3M | $79.00 | MC-3 (B) |
| hbase-adhoc-34 | REACHED_CONFIRMED | 5h15m | 91.7M | $84.39 |  |
| hbase-adhoc-35 | REACHED_CONFIRMED | 4h17m | 74.1M | $52.04 |  |
| hbase-adhoc-37 | REACHED_CONFIRMED | 4h26m | 85.9M | $83.26 |  |

## Caveats

- hbase-adhoc-22 hit a Specula report-parser bug (a detail table counted as a summary row); fixed in `confirmlib._report_rows` and resumed.

Verification: `../batches/VERIFY-*.md` (independent reviewer against the source; the operator re-read the decisive code). No tests were rerun for verification.
