#!/usr/bin/env python3
"""report.py -- REPORT.md and results.tsv: per check the agent's claim, validation, review, time and usage."""
import json, os

R = "/bulk/codingagent"
KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
SYS = {"hdfs": "HDFS", "zk": "ZooKeeper", "hbase": "HBase", "solr": "Solr"}
Q = json.load(open(f"{R}/queue.json"))


def load(p):
    return json.load(open(p)) if os.path.exists(p) else None


rows = []
for c in Q:
    run = load(f"{R}/cases/{c}/run.json") or {"sessions": [], "state": "-", "active_s": 0, "wait_s": 0}
    val = load(f"{R}/cases/{c}/validation.json") or {}
    rev = load(f"{R}/cases/{c}/review.json") or {}
    tot = dict.fromkeys(KEYS, 0); cost = 0.0
    for s in run["sessions"]:
        u = s.get("usage") or s.get("usage_fallback") or {}
        for k in KEYS:
            tot[k] += u.get(k) or 0
        cost += s.get("total_cost_usd") or 0
    res = run.get("result") or {}
    rows.append({
        "case": c, "system": SYS[c.split("-")[0]], "agent_state": run["state"],
        "claimed": bool(res.get("found")), "validation": val.get("verdict", "-"),
        "review": rev.get("verdict", "-"), "severity": rev.get("severity") or "",
        "active_h": round(run["active_s"] / 3600, 3), "wait_h": round(run["wait_s"] / 3600, 3),
        "sessions": len(run["sessions"]), "tokens": sum(tot.values()), **tot, "cost_usd": round(cost, 2),
        "test": res.get("test", "") if res.get("found") else "", "summary": rev.get("summary", "")})
order = {"HDFS": 0, "Solr": 1, "HBase": 2, "ZooKeeper": 3}
rows.sort(key=lambda r: (order[r["system"]], r["case"]))
cols = list(rows[0].keys())
with open(f"{R}/results.tsv", "w") as f:
    f.write("\t".join(cols) + "\n")
    for r in rows:
        f.write("\t".join(str(r[k]) for k in cols) + "\n")


def fmt_tok(n):
    return f"{n/1e6:.2f}M"


def hm(h):
    m = round(h * 60); return f"{m//60}h{m%60:02d}m"


L = ["# Coding-agent baseline: results on the 84 ad hoc checks", "",
     "Setup: `README.md`. Claude Code 2.1.319, `claude-opus-5-5[1m]`, effort high, one prompt per check (the paper's four parts), "
     "no git history, no network except the model API, 8 h budget per check. Time is the agent's active time (usage-limit waits excluded); "
     "tokens are input + output + cache writes + cache reads, as the CLI reports them, including subagents; cost is the CLI's list-price estimate.", "",
     "- **Validated**: the paper's criterion. The agent's test, run on an unmodified copy of the system (only its test files carried over), "
     "throws the check's exception from the check's line.",
     "- **Bug (reviewed)**: a validated reproduction that an independent source review (`REVIEW-RUBRIC.md`) judged a real bug by realistic means. "
     "The other validated ones are the check rejecting by design (BY_DESIGN) or reached by an unrealistic test (UNREALISTIC).", "",
     "## Summary", "", "| system | checks | claimed | validated | bug (reviewed) | by design | unrealistic | agent time | tokens | cost |",
     "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
for sysname in ["HDFS", "Solr", "HBase", "ZooKeeper", None]:
    rs = [r for r in rows if sysname is None or r["system"] == sysname]
    L.append("| " + " | ".join([sysname or "**total**", str(len(rs)), str(sum(r["claimed"] for r in rs)),
                                 str(sum(r["validation"] == "REPRODUCED" for r in rs)),
                                 str(sum(r["review"] == "BUG" for r in rs)), str(sum(r["review"] == "BY_DESIGN" for r in rs)),
                                 str(sum(r["review"] == "UNREALISTIC" for r in rs)),
                                 hm(sum(r["active_h"] for r in rs)), fmt_tok(sum(r["tokens"] for r in rs)),
                                 f"${sum(r['cost_usd'] for r in rs):,.0f}"]) + " |")
L += ["", "## Bugs (validated and reviewed as real), with the time and usage of their check", "",
      "| case | severity | bug | agent time | tokens | output tokens | cost |", "| --- | --- | --- | ---: | ---: | ---: | ---: |"]
for r in rows:
    if r["review"] == "BUG":
        L.append(f"| {r['case']} | {r['severity']} | {r['summary']} | {hm(r['active_h'])} | {fmt_tok(r['tokens'])} | "
                 f"{r['output_tokens']:,} | ${r['cost_usd']:.2f} |")
L += ["", "## Every check", "",
      "| case | claimed | validated | review | agent time | waits | tokens | cost |", "| --- | --- | --- | --- | ---: | ---: | ---: | ---: |"]
for r in rows:
    L.append(f"| {r['case']} | {'yes' if r['claimed'] else 'no'} | {r['validation']} | {r['review']} | {hm(r['active_h'])} | "
             f"{hm(r['wait_h'])} | {fmt_tok(r['tokens'])} | ${r['cost_usd']:.2f} |")
L += ["", "## Notes", "",
      "- **Overlap with the paper's Table 2** (same defect, from the bug descriptions): hdfs-adhoc-11 = HD1 (Balancer keeps a rejected "
      "encryption key), hbase-adhoc-22 = HB1 (truncation leaves the cached region count stale), zk-adhoc-b6 = ZK1 (observer misses "
      "proposals forwarded during sync), zk-adhoc-b5 = ZK2 (gap in a follower's txn log), zk-adhoc-b1 = ZK3 (partial quota creation), "
      "zk-adhoc-b3 = ZK5 (cleanup deletes a re-created node).",
      "- The ZooKeeper b1-b6, HBase 04/07/13/22/34 and HDFS 12 checks start from ported workloads (the same starting tests the paper's "
      "tool used); several of them set up the scenario around the bug, which the agent then only has to perturb.",
      "- Agents finished fast: median 7 min of agent time, longest 52 min; none came near its 8 h budget. Waits are usage-limit pauses of the "
      "shared account (the last HDFS runs waited about 1.5 h).",
      "- Leakage audit (2026-11-07): 0 agent transcripts mention GraphChecker/Causym/Specula; no WebSearch/WebFetch call; no "
      "connection refused by the egress proxy on any node (no attempt to reach anything but the model API); no agent changed "
      "production code (validation.json `production_changes` empty for all).",
      "- Validation matcher: accepts the frame on any line of the check's throw statement (the JVM records the constructor's line) "
      "and any method of the check's file (hbase-adhoc-35's check is in an anonymous visitor). Earlier verdicts were re-run after "
      "these two fixes; superseded verdicts are in `cases/<case>/logs/validation.v1.json`.",
      "- Reviews are first-pass source reviews by independent reviewer agents (`cases/<case>/review.json`, rubric `REVIEW-RUBRIC.md`), "
      "with operator spot checks of zk-adhoc-10, zk-adhoc-b3 and hbase-adhoc-21; BY_DESIGN/BUG calls marked as judgment calls in the "
      "reviews (e.g. solr-adhoc-07/13, hdfs-adhoc-20) can go either way."]
open(f"{R}/REPORT.md", "w").write("\n".join(L) + "\n")
print("\n".join(L[:20]))
