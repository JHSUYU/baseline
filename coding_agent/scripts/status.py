#!/usr/bin/env python3
"""status.py [--tsv] -- one row per case: agent state, active time, tokens, cost, claim, validation."""
import json, os, sys

R = "/bulk/codingagent"
Q = json.load(open(f"{R}/queue.json")) if os.path.exists(f"{R}/queue.json") else {}
KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def usage(run):
    tot = dict.fromkeys(KEYS, 0)
    cost = 0.0
    for s in run["sessions"]:
        u = s.get("usage") or s.get("usage_fallback") or {}
        for k in KEYS:
            tot[k] += u.get(k) or 0
        cost += s.get("total_cost_usd") or 0
    return tot, cost


def hms(s):
    s = int(s); return f"{s//3600}h{s%3600//60:02d}m"


rows = []
for c in sorted(os.listdir(f"{R}/cases")):
    p = f"{R}/cases/{c}/run.json"
    if not os.path.exists(p):
        continue
    run = json.load(open(p))
    tot, cost = usage(run)
    res = run.get("result") or {}
    v = {}
    if os.path.exists(f"{R}/cases/{c}/validation.json"):
        v = json.load(open(f"{R}/cases/{c}/validation.json"))
    rows.append([c, run["state"], hms(run["active_s"]), hms(run["wait_s"]), str(len(run["sessions"])),
                 str(sum(tot.values())), str(tot["output_tokens"]), str(tot["cache_read_input_tokens"]),
                 f"{cost:.2f}", "yes" if res.get("found") else ("no" if run.get("result") else "-"),
                 v.get("verdict", "-"), Q.get(c, {}).get("node", "-")])
hdr = ["case", "state", "active", "waits", "sessions", "tokens", "output", "cache_read", "cost_usd", "claimed",
       "validation", "node"]
if "--tsv" in sys.argv:
    print("\t".join(hdr)); [print("\t".join(r)) for r in rows]
else:
    w = [max(len(x) for x in col) for col in zip(hdr, *rows)]
    for r in [hdr] + rows:
        print("  ".join(x.ljust(n) for x, n in zip(r, w)))
