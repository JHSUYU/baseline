# ZooKeeper: Specula ad hoc coordination results

One Specula run per check; model `claude-opus-5-5[1m]`. Effort `max` for runs before 2026-11-04 and `high` after (counted together, owner). Time is active time: quota sleeps are excluded (`tools/active_time.py`). Tokens and cost include usage overwritten by restarts (`tools/case_tally.py`).

## Summary

- Checks: 16; verdicts: INCOMPLETE 1, REACHED_CONFIRMED 15.
- Total: 65h23m active, 1611.8M tokens, $1323.40.
- Verified bugs (real, severe, fail the ad hoc check): **7** (see `VERIFIED-BUGS.md`).

## Per check

| check | verdict | active time | tokens | cost | verified bugs |
| --- | --- | ---: | ---: | ---: | --- |
| zk-adhoc-01 | REACHED_CONFIRMED | 4h59m | 148.6M | $105.09 |  |
| zk-adhoc-02 | REACHED_CONFIRMED | 4h01m | 96.2M | $74.66 |  |
| zk-adhoc-03 | REACHED_CONFIRMED | 3h10m | 90.2M | $66.33 |  |
| zk-adhoc-04 | INCOMPLETE | 5h38m | 128.8M | $96.51 | MC-2 (B) |
| zk-adhoc-06 | REACHED_CONFIRMED | 3h58m | 153.0M | $106.71 |  |
| zk-adhoc-07 | REACHED_CONFIRMED | 4h12m | 95.9M | $80.77 |  |
| zk-adhoc-10 | REACHED_CONFIRMED | 4h51m | 92.1M | $96.34 |  |
| zk-adhoc-11 | REACHED_CONFIRMED | 4h56m | 110.2M | $96.99 | MC-3 (B), CR-1 (B) |
| zk-adhoc-12 | REACHED_CONFIRMED | 3h49m | 86.2M | $71.14 |  |
| zk-adhoc-13 | REACHED_CONFIRMED | 7h42m | 108.0M | $114.88 |  |
| zk-adhoc-b1 | REACHED_CONFIRMED | 2h53m | 102.2M | $75.13 |  |
| zk-adhoc-b2 | REACHED_CONFIRMED | 2h45m | 84.2M | $61.38 | MC-1 (B) |
| zk-adhoc-b3 | REACHED_CONFIRMED | 2h49m | 100.6M | $74.96 | MC-1 (A), CR-3 (B) |
| zk-adhoc-b4 | REACHED_CONFIRMED | 2h27m | 74.4M | $51.89 |  |
| zk-adhoc-b5 | REACHED_CONFIRMED | 3h43m | 86.0M | $90.21 |  |
| zk-adhoc-b6 | REACHED_CONFIRMED | 3h21m | 55.3M | $60.40 | MC-3 (B) |

## Caveats

- zk-adhoc-04 is final as incomplete (owner): a model safeguard flag stopped CR-5's conversation; CR-6, CR-7 and MC-3 stayed unfinished. Its usage is counted.

Verification: `../batches/VERIFY-*.md` (independent reviewer against the source; the operator re-read the decisive code). No tests were rerun for verification.
