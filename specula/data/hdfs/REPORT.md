# HDFS: Specula ad hoc coordination results

One Specula run per check; model `claude-opus-5-5[1m]`. Effort `max` for runs before 2026-11-04 and `high` after (counted together, owner). Time is active time: quota sleeps are excluded (`tools/active_time.py`). Tokens and cost include usage overwritten by restarts (`tools/case_tally.py`).

## Summary

- Checks: 36; verdicts: NOT_REACHED_BOUNDED 10, REACHED_CONFIRMED 26.
- Total: 191h39m active, 10776.1M tokens, $5959.28.
- Verified bugs (real, severe, fail the ad hoc check): **11** (see `VERIFIED-BUGS.md`).

## Per check

| check | verdict | active time | tokens | cost | verified bugs |
| --- | --- | ---: | ---: | ---: | --- |
| hdfs-adhoc-05 | NOT_REACHED_BOUNDED | 4h38m | 174.7M | $96.71 |  |
| hdfs-adhoc-06 | NOT_REACHED_BOUNDED | 5h23m | 328.3M | $178.14 |  |
| hdfs-adhoc-07 | REACHED_CONFIRMED | 5h48m | 303.2M | $159.65 | MC-1 (A) |
| hdfs-adhoc-08 | REACHED_CONFIRMED | 5h53m | 253.0M | $148.60 | MC-1 (A), MC-2 (B) |
| hdfs-adhoc-09 | REACHED_CONFIRMED | 5h26m | 378.8M | $190.40 |  |
| hdfs-adhoc-10 | REACHED_CONFIRMED | 3h52m | 199.4M | $115.54 |  |
| hdfs-adhoc-11 | REACHED_CONFIRMED | 6h18m | 470.5M | $259.50 | MC-4 (A), MC-1 (B) |
| hdfs-adhoc-12 | REACHED_CONFIRMED | 8h10m | 593.0M | $322.49 |  |
| hdfs-adhoc-14 | REACHED_CONFIRMED | 4h11m | 314.4M | $152.01 | MC-1 (B) |
| hdfs-adhoc-15 | NOT_REACHED_BOUNDED | 6h20m | 396.9M | $204.79 |  |
| hdfs-adhoc-16 | NOT_REACHED_BOUNDED | 7h50m | 355.3M | $152.67 |  |
| hdfs-adhoc-19 | NOT_REACHED_BOUNDED | 5h24m | 217.0M | $107.65 |  |
| hdfs-adhoc-20 | REACHED_CONFIRMED | 6h24m | 453.8M | $269.16 |  |
| hdfs-adhoc-21 | NOT_REACHED_BOUNDED | 4h03m | 164.6M | $90.98 |  |
| hdfs-adhoc-22 | NOT_REACHED_BOUNDED | 5h39m | 242.5M | $118.50 |  |
| hdfs-adhoc-23 | NOT_REACHED_BOUNDED | 5h33m | 280.4M | $142.13 |  |
| hdfs-adhoc-24 | REACHED_CONFIRMED | 6h09m | 552.9M | $297.19 | MC-2 (A), CR-6 (B), MC-3 (B) |
| hdfs-adhoc-25 | REACHED_CONFIRMED | 4h37m | 285.8M | $149.92 |  |
| hdfs-adhoc-26 | REACHED_CONFIRMED | 4h10m | 429.8M | $236.47 | MC-1 (B) |
| hdfs-adhoc-27 | NOT_REACHED_BOUNDED | 5h18m | 375.6M | $197.74 |  |
| hdfs-adhoc-28 | REACHED_CONFIRMED | 5h11m | 316.8M | $183.54 |  |
| hdfs-adhoc-29 | REACHED_CONFIRMED | 4h13m | 284.3M | $147.57 |  |
| hdfs-adhoc-30 | REACHED_CONFIRMED | 3h50m | 417.3M | $210.15 |  |
| hdfs-adhoc-31 | REACHED_CONFIRMED | 6h11m | 445.2M | $251.87 |  |
| hdfs-adhoc-33 | REACHED_CONFIRMED | 2h54m | 193.4M | $97.49 |  |
| hdfs-adhoc-34 | REACHED_CONFIRMED | 4h25m | 319.2M | $219.24 |  |
| hdfs-adhoc-35 | REACHED_CONFIRMED | 6h20m | 257.1M | $149.47 |  |
| hdfs-adhoc-37 | REACHED_CONFIRMED | 5h40m | 274.2M | $151.74 |  |
| hdfs-adhoc-38 | REACHED_CONFIRMED | 3h04m | 140.2M | $82.19 | MC-1 (A) |
| hdfs-adhoc-39 | REACHED_CONFIRMED | 7h41m | 176.6M | $109.23 |  |
| hdfs-adhoc-40 | REACHED_CONFIRMED | 7h27m | 366.8M | $234.67 |  |
| hdfs-adhoc-45 | REACHED_CONFIRMED | 4h40m | 176.7M | $126.44 |  |
| hdfs-adhoc-48 | NOT_REACHED_BOUNDED | 7h14m | 148.0M | $115.44 |  |
| hdfs-adhoc-49 | REACHED_CONFIRMED | 4h16m | 194.3M | $106.86 |  |
| hdfs-adhoc-50 | REACHED_CONFIRMED | 3h53m | 171.5M | $106.57 |  |
| hdfs-adhoc-52 | REACHED_CONFIRMED | 3h16m | 124.7M | $76.58 |  |

## Caveats

- Runs before 2026-11-02 were not fully independent: Claude Code auto-memory let agents read notes from earlier runs on the same node.
- hdfs-adhoc-05..09 started before the per-invocation log markers, so their active time is understated.

Verification: `../batches/VERIFY-*.md` (independent reviewer against the source; the operator re-read the decisive code). No tests were rerun for verification.
