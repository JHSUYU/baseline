"""Optional static MAY producer hints, separate from observed causal closure."""

from __future__ import annotations

import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=4)
def rpc_producer_sites(path: str, sha256: str, target_site: str) -> frozenset[str]:
    """Find RPC doors whose enclosing method MAY produce a target-region value.

    The SHA is part of the cache key and is checked by campaign admission and
    before every trial. This graph is only a queue hint; it never supplies a
    runtime edge or closure membership.
    """
    methods_by_region: dict[str, set[str]] = defaultdict(set)
    predecessors: dict[str, set[str]] = defaultdict(set)
    doors: dict[str, tuple[str, bool]] = {}
    target_regions: set[str] = set()
    with Path(path).open(encoding="utf-8") as source:
        for number, line in enumerate(source, 1):
            row = json.loads(line)
            if row.get("kind") != "STATIC_SCOPE_SITE":
                continue
            role = row.get("role")
            if role == "STATIC_REGION_METHOD":
                methods_by_region[row["regionId"]].add(row["vmMethod"])
            elif role == "STATIC_VALUE_EDGE":
                predecessors[row["consumerMethod"]].add(row["producerMethod"])
            elif role == "TARGET_SITE" and row.get("siteId") == target_site:
                target_regions.add(row["regionId"])
            elif role == "DOOR_SITE":
                site = row["siteId"]
                rpc = (row.get("transport") == "RPC" or
                       str(row.get("exceptionClass", "")).endswith(
                           ".ServiceException"))
                prior = doors.get(site)
                method = row.get("vmSite")
                if not isinstance(method, str) or not method:
                    raise ValueError(f"static MAY door lacks method at row {number}")
                if prior is not None and prior[0] != method:
                    raise ValueError(f"static MAY door has conflicting methods: {site}")
                doors[site] = (method, rpc or (prior[1] if prior else False))
    if not target_regions:
        raise ValueError("static MAY map lacks exact target site")
    reached = set().union(*(methods_by_region[region]
                            for region in target_regions))
    frontier = list(reached)
    for consumer in frontier:
        for producer in predecessors.get(consumer, ()):
            if producer not in reached:
                reached.add(producer)
                frontier.append(producer)
    return frozenset(site for site, (method, rpc) in doors.items()
                     if rpc and method in reached)
