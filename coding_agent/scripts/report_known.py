#!/usr/bin/env python3
"""report_known.py -- known/REPORT.md and known/results.tsv: the 14 known bugs at their buggy versions."""
import json, os

R = "/bulk/codingagent"
KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
BUGS = [("hdfs-adhoc-k1", "HDFS-11741", "Balancer block moves fail"), ("hdfs-adhoc-k2", "HDFS-17383", "Block transfers fail"),
        ("hdfs-adhoc-k3", "HDFS-12931", "File checksum fails"), ("hdfs-adhoc-k4", "HDFS-5766", "Healthy DataNode marked dead"),
        ("hdfs-adhoc-k5", "HDFS-10609", "Pipeline recovery aborts client"), ("hdfs-adhoc-k6", "HDFS-14075", "NameNode crashes with NPE"),
        ("hdfs-adhoc-k7", "HDFS-14311", "DataNode upgrade fails"), ("solr-adhoc-k1", "SOLR-9440", "Client caches stale state"),
        ("solr-adhoc-k2", "SOLR-6101", "Shard splitting fails"), ("solr-adhoc-k3", "SOLR-6197", "Collection migration fails"),
        ("hbase-adhoc-k1", "HBASE-15039", "Token authentication fails"), ("hbase-adhoc-k2", "HBASE-20642", "Adding column family fails"),
        ("zk-adhoc-k1", "ZOOKEEPER-710", "Permanent session-moved errors"), ("zk-adhoc-k2", "ZOOKEEPER-2886", "Multi-op session-moved errors")]


def load(p):
    return json.load(open(p)) if os.path.exists(p) else {}


def hm(s):
    m = round(s / 60); return f"{m//60}h{m%60:02d}m"


rows = []
for c, jira, title in BUGS:
    run = load(f"{R}/cases/{c}/run.json") or {"sessions": [], "active_s": 0, "wait_s": 0, "state": "-"}
    val, fx, rev = load(f"{R}/cases/{c}/validation.json"), load(f"{R}/cases/{c}/validation-fixed.json"), load(f"{R}/cases/{c}/review-known.json")
    tot = dict.fromkeys(KEYS, 0); cost = 0.0
    for s in run["sessions"]:
        u = s.get("usage") or s.get("usage_fallback") or {}
        for k in KEYS:
            tot[k] += u.get(k) or 0
        cost += s.get("total_cost_usd") or 0
    res = run.get("result") or {}
    rows.append({"case": c, "jira": jira, "bug": title, "agent_state": run["state"], "claimed": bool(res.get("found")),
                 "validation": val.get("verdict", "-"), "fixed_version": fx.get("verdict", "-"),
                 "detected": rev.get("detected", "-"), "active_s": round(run["active_s"]), "wait_s": round(run["wait_s"]),
                 "sessions": len(run["sessions"]), "tokens": sum(tot.values()), **tot, "cost_usd": round(cost, 2),
                 "test": res.get("test", "") if res.get("found") else "", "finding": rev.get("finding", "")})
with open(f"{R}/known/results.tsv", "w") as f:
    f.write("\t".join(rows[0]) + "\n")
    for r in rows:
        f.write("\t".join(str(v) for v in r.values()) + "\n")

det = [r for r in rows if r["detected"] == "yes"]
part = [r for r in rows if r["detected"] == "partly"]
L = ["# Coding-agent baseline on 14 known bugs, at their buggy versions", "",
     "Same agent and prompt as the 84 checks (`../README.md`): Claude Code 2.1.319, `claude-opus-5-5[1m]`, effort high, "
     "one prompt per bug that gives **only the ad hoc check** the bug makes fail and a starting test (no bug, no JIRA). "
     "Each tree is the parent of the bug's fix, one commit `base`, no history (`README.md` here). "
     "Time is the agent's active time (usage-limit waits excluded); tokens are input + output + cache writes + cache reads, "
     "including subagents; cost is the CLI's list-price estimate.", "",
     f"**Result: {len(det)} detected" + (f", {len(part)} partly" if part else "") + f", {14 - len(det) - len(part)} not detected.**", "",
     "Detected = a validated reproduction (the check's exception at the check's line on the unmodified buggy tree) whose root "
     "cause is the bug's defect (`CRITERIA.md`, written before the runs), judged by an independent source review against "
     "the JIRA's fix; `fixed version` is the agent's test re-run with the fix's production changes applied.", "",
     "| bug | case | claimed | validated | fixed version | detected | agent time | tokens | output tokens | cost |",
     "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |"]
for r in rows:
    L.append(f"| {r['jira']} {r['bug']} | {r['case']} | {'yes' if r['claimed'] else 'no'} | {r['validation']} | {r['fixed_version']} | "
             f"{r['detected']} | {hm(r['active_s'])} | {r['tokens']/1e6:.1f}M | {r['output_tokens']:,} | ${r['cost_usd']:.2f} |")
L.append(f"| **total** | | {sum(r['claimed'] for r in rows)} | {sum(r['validation']=='REPRODUCED' for r in rows)} | | "
         f"{len(det)} | {hm(sum(r['active_s'] for r in rows))} | {sum(r['tokens'] for r in rows)/1e6:.1f}M | "
         f"{sum(r['output_tokens'] for r in rows):,} | ${sum(r['cost_usd'] for r in rows):.2f} |")
L += ["", "## Findings", ""]
for r in rows:
    L.append(f"- **{r['case']} ({r['jira']})**: {r['finding'] or '-'}")
L += ["", "## Notes", "",
      "- **Same check, other bug.** Three non-detections reproduced a real failure of the same check through another known "
      "defect: hdfs-adhoc-k3 (HDFS-12931) and hdfs-adhoc-k5 (HDFS-10609) found HDFS-17383's root cause (a DataNode's currentKey "
      "taken from the standby NameNode, breaking DataNode-to-DataNode transfers), and hdfs-adhoc-k4 (HDFS-5766) found HDFS-11741 "
      "(the balancer's never-renewed encryption key). They do not count for their own case. hdfs-adhoc-k2 (HDFS-17383 itself) "
      "found a different weakness (lost key-update heartbeat responses, injected by a spy) that the fix does not change. "
      "solr-adhoc-k1 found a failed SPLITSHARD leaving a CONSTRUCTION sub-shard, not the stale watched-collection state. "
      "zk-adhoc-k2 found ZOOKEEPER-710's owner divergence through setData (connection torn down), not the multi-only path.",
      "- **Fixed version.** For 7 of the 8 detected bugs the agent's test no longer fails the check once the fix's production "
      "changes are applied; for ZOOKEEPER-710 (a fix that handles the exception) the check fires once but the connection is "
      "closed, so the permanent error is gone. For all 6 non-detections the failure persists on the fixed version.",
      "- **Model memory.** In hdfs-adhoc-k1 and hdfs-adhoc-k4 the agent named HDFS-11741 from memory, and in zk-adhoc-k2 named "
      "ZOOKEEPER-2886 as a possibility, each only in its final write-up after the reproduction; no tree, cache or prompt holds "
      "a JIRA key or fix hash (ZOOKEEPER-710 appears in a genuine source comment of the zk-adhoc-k2 tree, as in upstream). "
      "That the model may know these old bugs from training cannot be ruled out; the runs were fast (median 5.5 min of agent time, longest 17 min, no usage-limit waits).",
      "- **Leakage audit:** no transcript mentions Specula, GraphChecker or Causym; no WebSearch/WebFetch call; no proxy "
      "denial during these runs; no agent changed production code.",
      "- **Superseded run:** the first zk-adhoc-k1 run (5 min) was stopped and redone: its tree's history tracked build "
      "output of Specula's instrumented build (`superseded/README.md`).",
      "- Reviews: `cases/<case>/review-known.json`, by independent reviewer agents against `CRITERIA.md` and the fix diff."]
open(f"{R}/known/REPORT.md", "w").write("\n".join(L) + "\n")
print("\n".join(L[:30]))
