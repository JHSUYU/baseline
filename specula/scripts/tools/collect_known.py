#!/usr/bin/env python3
"""Collect the known-bug study's detected findings into known-bugs/: TLC files, reproduction, cost."""
import json, re, shutil, csv
from pathlib import Path
R = Path("/bulk/specula-adhoc"); D = R / "known-bugs"
SYS = {"hdfs": "hdfs", "zk": "zookeeper", "hbase": "hbase", "solr": "solr"}
rows = [r for r in csv.DictReader(open("/users/ZhenyuLi/bugstudy/RESULTS.tsv"), delimiter="\t") if not r["case"].startswith("#")]
if D.exists(): shutil.rmtree(D)
D.mkdir()
for r in rows:
    if r["detected"] == "no": r["dir"] = ""; r["tlc"] = ""; continue
    s = SYS[r["case"].split("-")[0]]; c, f = r["case"], r["finding"]
    src = R / s / "bugs" / c / f; dst = D / f"{r['jira']}-{c}-{f}"
    shutil.copytree(src, dst, symlinks=True, ignore=shutil.ignore_patterns("states", "worktree"))
    rr = dst / "RERUN.md"; t = rr.read_text()
    t = t.replace(str(src), str(dst)).replace(f"/tmp/rerun-{c}-{f}/states", f"/tmp/rerun-{c}-{f}").replace("\njava -XX", "\n/bulk/specula-adhoc/jdk/jdk-21.0.13+9/bin/java -XX")
    rr.write_text(t)
    cfg = re.search(r"- Config: `([^`]+)`", t)
    r["dir"] = dst.name; r["tlc"] = cfg[1] if cfg else "(code-review finding: reproduced by test, no TLC)"
json.dump(rows, open(D / "bugs.json", "w"), indent=1)
print(sum(1 for r in rows if r["dir"]))
