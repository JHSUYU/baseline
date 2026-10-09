#!/usr/bin/env python3
"""Precompute independent later rounds; campaign.py alone updates result.json."""
from concurrent.futures import ThreadPoolExecutor
from campaign import plans, run_one

selectors = plans()
with ThreadPoolExecutor(max_workers=2) as pool:
    futures = [pool.submit(run_one, 'r%03d' % i, selectors[i - 1])
               for i in range(61, 81)]
    for future in futures:
        future.result()
