#!/usr/bin/env python3
"""queue.py -- run the coding agent on all 84 ad hoc checks, at most SLOTS per node at a time.

For each case: prepare (on this node), start bin/driver.py on a node with a free slot, and when the
driver has finished, run bin/validate.py on the same node if the agent claims a reproduction.
A driver that died is restarted (it resumes from run.json).  State: queue.json; log: logs/queue.log.
Hold a case by creating cases/<case>/HOLD.
"""
import json, os, subprocess, time

R = "/bulk/codingagent"
NODES = ["node0", "node1", "node2", "node3", "node4"]
SLOTS = 2
HDFS = "05 06 07 08 09 10 11 12 14 15 16 19 20 21 22 23 24 25 26 27 28 29 30 31 33 34 35 37 38 39 40 45 48 49 50 52".split()
ZK = "01 02 03 04 06 07 10 11 12 13 b1 b2 b3 b4 b5 b6".split()
HB = "04 07 08 10 11 12 13 14 15 19 20 21 22 24 28 31 34 35 37".split()
SOLR = "05 07 09 10 13 14 19 21 22 31 38 39 40".split()
lists = [[f"zk-adhoc-{x}" for x in ZK], [f"hdfs-adhoc-{x}" for x in HDFS], [f"hbase-adhoc-{x}" for x in HB],
         [f"solr-adhoc-{x}" for x in SOLR]]
CASES = []
while any(lists):           # interleave the systems
    for l in lists:
        if l:
            CASES.append(l.pop(0))
assert len(CASES) == 84, len(CASES)
# KNOWN=1: the 14 known bugs at their buggy versions (bin/prepare_known.py), own queue state and log.
KNOWN = os.environ.get("KNOWN") == "1"
if KNOWN:
    CASES = [f"{s}-adhoc-k{i}" for s, n in (("hdfs", 7), ("solr", 3), ("hbase", 2), ("zk", 2)) for i in range(1, n + 1)]
    CASES = [CASES[i] for i in (0, 7, 10, 12, 1, 8, 11, 13, 2, 9, 3, 4, 5, 6)]   # interleave the systems
QLOG = f"{R}/logs/queue-known.log" if KNOWN else f"{R}/logs/queue.log"


def log(msg):
    with open(QLOG, "a") as f:
        f.write(time.strftime("%Y-%m-%dT%H:%M:%SZ ", time.gmtime()) + msg + "\n")


def ssh(node, cmd, **kw):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", node, cmd], capture_output=True, text=True, **kw)


def run_state(c):
    try:
        return json.load(open(f"{R}/cases/{c}/run.json"))["state"]
    except Exception:
        return None


def alive(node, c, script):
    return ssh(node, f"pgrep -f '[b]in/{script} {c}$' >/dev/null && echo yes").stdout.strip() == "yes"


qpath = f"{R}/known/queue.json" if KNOWN else f"{R}/queue.json"
Q = json.load(open(qpath)) if os.path.exists(qpath) else {}


def save():
    json.dump(Q, open(qpath + ".tmp", "w"), indent=1)
    os.replace(qpath + ".tmp", qpath)


log(f"queue started: {len(CASES)} cases, {SLOTS} slots on each of {NODES}")
while True:
    # 1. Update running cases.
    for c, e in Q.items():
        if e["status"] == "running":
            st = run_state(c)
            if st in ("done", "budget", "error"):
                claimed = bool((json.load(open(f"{R}/cases/{c}/run.json")).get("result") or {}).get("found"))
                if claimed:
                    ssh(e["node"], f"cd {R} && (nohup python3 -I bin/validate.py {c} > cases/{c}/logs/validate.out 2>&1 &)")
                    e["status"] = "validating"; log(f"{c}: agent {st}, claims a reproduction; validating on {e['node']}")
                else:
                    e["status"] = "finished"; log(f"{c}: agent {st}, no reproduction claimed")
            elif not alive(e["node"], c, "driver.py"):
                e["restarts"] = e.get("restarts", 0) + 1
                if e["restarts"] > 3:
                    e["status"] = "needs-operator"; log(f"{c}: driver died {e['restarts']} times")
                else:
                    ssh(e["node"], f"cd {R} && (nohup python3 -I bin/driver.py {c} >> cases/{c}/logs/driver.out 2>&1 &)")
                    log(f"{c}: driver not running (state {st}); restarted on {e['node']}")
        elif e["status"] == "validating":
            if os.path.exists(f"{R}/cases/{c}/validation.json") and not alive(e["node"], c, "validate.py"):
                v = json.load(open(f"{R}/cases/{c}/validation.json"))["verdict"]
                e["status"] = "finished"; e["validation"] = v; log(f"{c}: validation {v}")
            elif not alive(e["node"], c, "validate.py"):
                e["status"] = "validation-failed"; log(f"{c}: validate.py died without a verdict")
    save()
    # 2. Fill free slots.
    busy = {n: 0 for n in NODES}
    for e in Q.values():
        if e["status"] in ("running", "validating"):
            busy[e["node"]] += 1
    for c in CASES:
        if c in Q or os.path.exists(f"{R}/cases/{c}/HOLD"):
            continue
        free = [n for n in NODES if busy[n] < SLOTS]
        if not free:
            break
        node = min(free, key=lambda n: busy[n])
        r = subprocess.run([f"{R}/bin/prepare.sh", c], capture_output=True, text=True)
        if r.returncode != 0:
            Q[c] = {"status": "prepare-failed", "error": r.stderr[-2000:]}; log(f"{c}: prepare failed"); save(); continue
        ssh(node, f"cd {R} && (nohup python3 -I bin/driver.py {c} >> cases/{c}/logs/driver.out 2>&1 &)")
        Q[c] = {"status": "running", "node": node, "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        busy[node] += 1
        log(f"{c}: started on {node}")
        save()
    if all(c in Q and Q[c]["status"] not in ("running", "validating") for c in CASES):
        log("all cases finished"); break
    time.sleep(60)
