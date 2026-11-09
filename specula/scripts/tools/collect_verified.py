#!/usr/bin/env python3
"""Collect the tier A/B verified bugs into verified-bugs/: TLC files, reproduction, and cost."""
import json, re, shutil, glob
from pathlib import Path
R = Path("/bulk/specula-adhoc"); D = R / "verified-bugs"
BUGS = [  # system, case, finding, tier, same defect as, one line
 ("hdfs","hdfs-adhoc-07","MC-1","A","","JN purge marks a restarted JN's live segment .stale; an acknowledged edit is lost after failover"),
 ("hdfs","hdfs-adhoc-11","MC-4","A","","FileChecksumHelper retry does not restore `remaining`; getFileChecksum silently returns a wrong checksum"),
 ("hdfs","hdfs-adhoc-38","MC-1","A","38/MC-2","LAZY_PERSIST inherited by existing files; append refused, scrubber deletes DISK files"),
 ("hdfs","hdfs-adhoc-24","MC-2","A","26/MC-3","disk formatted during an unfinalized upgrade gets the new cTime and no previous/; rollback cannot complete"),
 ("hdfs","hdfs-adhoc-08","MC-1","A","","epoch selection reads only a quorum's promises; a JN fences the new writer for its whole term"),
 ("hdfs","hdfs-adhoc-08","MC-2","B","","Journal.doRollback does not refresh cached epochs; a JN left up through rollback fences the next writer"),
 ("hdfs","hdfs-adhoc-24","CR-6","B","24/CR-2, 26/MC-2","failed block-pool dir still finalized; a volume that missed -rollback loses previous/"),
 ("hdfs","hdfs-adhoc-24","MC-3","B","","stale rolling-upgrade marker makes doFinalize delete a regular upgrade's previous/"),
 ("hdfs","hdfs-adhoc-11","MC-1","B","","heartbeat returns early in safe mode before the key update; encrypted reads fail after ~10 h"),
 ("hdfs","hdfs-adhoc-14","MC-1","B","","derived-QOP re-signs the forwarded token with the DN's key and keeps the keyId"),
 ("hdfs","hdfs-adhoc-26","MC-1","B","","DN doUpgrade deletes an existing previous/; a DN down during one rollback is silently re-upgraded"),
 ("zookeeper","zk-adhoc-b3","MC-1","A","b3/CR-2","silent, durable delete of a client's PERSISTENT znode; default config"),
 ("zookeeper","zk-adhoc-b3","CR-3","B","","after a live restore the manager scans the old tree forever and deletes restored nodes"),
 ("zookeeper","zk-adhoc-b2","MC-1","B","b2/MC-3","offer vanishes between list and read; participant goes FAILED and blocks the election"),
 ("zookeeper","zk-adhoc-11","MC-3","B","b5/MC-2","stop during sync skips the epoch write; the peer can never restart"),
 ("zookeeper","zk-adhoc-11","CR-1","B","","one failed epoch write leaves SNAP sync mode; an observer is wedged for good"),
 ("zookeeper","zk-adhoc-04","MC-2","B","","read-only server serves never-committed txns (run incomplete)"),
 ("zookeeper","zk-adhoc-b6","MC-3","B","","ObserverMaster eviction empties the queue and skips the gap check; observer silently misses a commit"),
 ("hbase","hbase-adhoc-11","MC-3","A","10/CR-1","truncate_region force-detaches a concurrent move's TRSP; region stuck CLOSING, unserved"),
 ("hbase","hbase-adhoc-11","MC-2","B","","split admits a CLOSED parent; rollback sets OPEN with no location; assign refused"),
 ("hbase","hbase-adhoc-04","MC-3","B","","new master forgets a quota DISABLE; raising the limit does nothing"),
 ("hbase","hbase-adhoc-08","MC-3","B","","rsgroup: meta assignment needs the namespace cache, which needs meta; master aborts"),
 ("hbase","hbase-adhoc-08","MC-1","B","","recovered namespace delete races quota init; the new master aborts"),
 ("hbase","hbase-adhoc-21","MC-4","B","22/CR-1","master rebuild counts region replicas, creates reserve primaries; valid creates refused after every restart"),
 ("hbase","hbase-adhoc-31","MC-3","B","","crashed RS both online and dead after failover; stays online for good, cluster shutdown never completes"),
]
def tok(d):
    u = d.get("usage") or {}
    return sum(u.get(k, 0) or 0 for k in ("input_tokens","output_tokens","cache_read_input_tokens","cache_creation_input_tokens")), d.get("total_cost_usd") or 0
tally = {}
for s in ("hdfs","zookeeper","hbase","solr"):
    for l in open(R/"batches"/f"final-{s}-tally.tsv"):
        c,*v = l.rstrip("\n").split("\t"); tally[c] = v
if D.exists(): shutil.rmtree(D)
rows = []
for s,c,f,tier,dup,line in BUGS:
    src = R/s/"bugs"/c/f; dst = D/f"{c}-{f}"
    shutil.copytree(src, dst, symlinks=True, ignore=shutil.ignore_patterns("states", "worktree"))
    rr = dst/"RERUN.md"; t = rr.read_text()
    t = t.replace(str(src), str(dst)).replace(f"/tmp/rerun-{c}-{f}/states", f"/tmp/rerun-{c}-{f}").replace("\njava -XX", "\n/bulk/specula-adhoc/jdk/jdk-21.0.13+9/bin/java -XX")
    rr.write_text(t)
    ct = cc = 0
    for u in (dst/"confirmation"/f).glob("*usage*.json"):
        try: a,b = tok(json.load(open(u))); ct += a; cc += b
        except Exception: pass
    cfg = re.search(r"- Config: `([^`]+)`", t); inv = re.search(r"Expect TLC to report: `([^`]+)`", t)
    rows.append(dict(system=s, case=c, finding=f, tier=tier, same_as=dup, bug=line, dir=dst.name,
        tlc_config=cfg[1] if cfg else "", expect=inv[1] if inv else "(code-review finding: no TLC counterexample)",
        case_time=tally[c][0], case_tokens=tally[c][1], case_cost=tally[c][2],
        confirm_tokens=f"{ct/1e6:.1f}M", confirm_cost=f"${cc:.2f}"))
json.dump(rows, open(D/"bugs.json","w"), indent=1)
print(len(rows))
