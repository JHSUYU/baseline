#!/usr/bin/env python3
"""validate.py <case> -- check an agent's claimed reproduction on an unmodified copy of the system.

1. List what the agent changed in its tree (git: modified tracked files and new files).  Changes to
   production sources or build files of the system are recorded and NOT carried over.
2. Prepare a fresh copy of the case (same tree, same dependency cache) under cases/<case>/validate/ and copy in
   only the agent's new or changed test-side files.
3. Run the agent's command there, in the same offline container setup, up to 3 times.
4. The reproduction holds if the output (console and test reports) has the target exception with a stack
   frame at the target file:line.

Writes cases/<case>/validation.json.
"""
import glob, json, os, re, shutil, subprocess, sys, time

import yaml

R = "/bulk/codingagent"
S = "/bulk/specula-adhoc"
case_id = sys.argv[1]
tries = int(sys.argv[2]) if len(sys.argv) > 2 else 3
cdir = f"{R}/cases/{case_id}"
agent = f"{cdir}/agent"
# FIXED=1 (known bugs): run the same test files on the fixed version instead (known/<case>/fixed).
FIXED = os.environ.get("FIXED") == "1"
SUF = "-fixed" if FIXED else ""
val = f"{cdir}/validate{SUF}"
tree = next(d for d in os.listdir(agent) if d in ("hadoop", "zookeeper", "hbase", "lucene-solr"))
t = yaml.safe_load(open(f"{cdir}/target.yaml"))
chk = t["check"]
res = json.load(open(f"{agent}/result.json"))
out = {"case": case_id, "claimed": bool(res.get("found")), "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def save():
    json.dump(out, open(f"{cdir}/validation{SUF}.json", "w"), indent=1)


if not res.get("found"):
    out["verdict"] = "NOT_CLAIMED"; save(); print(f"{case_id}: not claimed"); sys.exit(0)


def git(*a):
    return subprocess.run(["git", "-C", f"{agent}/{tree}", *a], capture_output=True, text=True).stdout


PROD = re.compile(r"(^|/)src/main/|^src/java/main/|^(solr|lucene)/[^/]+(/[^/]+)?/src/java/|(^|/)(pom\.xml|build\.xml|ivy\.xml|common-build\.xml)$")
changed = [l[3:].strip().strip('"') for l in git("status", "--porcelain", "--untracked-files=all").splitlines()]
changed = [c.split(" -> ")[-1] for c in changed]
prod = [c for c in changed if PROD.search(c)]
test_side = [c for c in changed if not PROD.search(c)]
out["changed_files"] = changed
out["production_changes"] = prod
out["production_diff"] = git("diff", "--", *prod)[:20000] if prod else ""

# Fresh copy, then only the test-side files.
if os.path.exists(val):
    subprocess.run(["rm", "-rf", val], check=True)
subprocess.run([f"{R}/bin/prepare.sh", case_id, val] if not FIXED else
               ["python3", "-I", f"{R}/bin/prepare_known.py", "copyfixed", case_id, val], check=True, capture_output=True)
for f in test_side:
    src, dst = f"{agent}/{tree}/{f}", f"{val}/{tree}/{f}"
    if os.path.isdir(src):
        continue
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
os.makedirs(f"{val}/home", exist_ok=True)

cmd = (res.get("command") or "").replace(agent, val)
# The standard command of the prompt, run on the agent's test: a fallback when the agent's own command does
# not reproduce (e.g. it carries commentary).
canon = None
test = (res.get("test") or "").strip()
if "#" in test:
    tcls, _, tmeth = test.partition("#")
    b = t["build"]["test_command"]
    canon = b.replace("<Class>", tcls.rsplit(".", 1)[-1] if "ant " in b else tcls).replace("<method>", tmeth)
    canon = canon.replace(" -o surefire:test ", " -o test ")
    if case_id.startswith("hbase-") and "-PrunAllTests" not in canon:
        canon = canon.replace(" -o test ", " -o test -PrunAllTests ")
commands = [c for c in (cmd, canon) if c]
if not commands:
    out["verdict"] = "NO_COMMAND"; save(); sys.exit(0)
out["command"] = cmd
out["canonical_command"] = canon

cls_simple = chk["method"].split("(")[0].rsplit(".", 1)[0].split(".")[-1]
meth = chk["method"].split("(")[0].rsplit(".", 1)[1]
fname = os.path.basename(chk["file"])
# The target line is where the throw statement starts; the JVM records the frame at the line of the
# exception's constructor call, which may be a later line of the same statement.  Accept the statement's lines.
src_lines = open(f"{val}/{tree}/{chk['file']}", errors="replace").read().splitlines()
first = chk["line"]
if FIXED:   # the fix may move the check: find the same statement (the buggy tree's line text) nearest the old line
    want = open(f"{R}/known/{case_id}/golden/{tree}/{chk['file']}", errors="replace").read().splitlines()[first - 1].strip()
    cands = [i + 1 for i, l in enumerate(src_lines) if l.strip() == want]
    first = min(cands, key=lambda n: abs(n - chk["line"])) if cands else first
    out["check_line_fixed"] = first if cands else None
last = first
while last < len(src_lines) and not src_lines[last - 1].rstrip().endswith(";") and last < first + 15:
    last += 1
lines_alt = "|".join(str(n) for n in range(first, last + 1))
out["accepted_lines"] = [first, last]
frame_re = re.compile(rf"at [\w.$]*\b{re.escape(cls_simple)}(\$[\w$]+)?\.[\w$<>]+\({re.escape(fname)}:({lines_alt})\)")   # file:line decide; the method may be an anonymous/inner class's
exc_simple = chk["thrown"].split(".")[-1]


def search(texts):
    for name, text in texts:
        lines = text.splitlines()
        for i, ln in enumerate(lines):
            if frame_re.search(ln):
                ctx = lines[max(0, i - 80):i + 1]
                for j in range(len(ctx) - 1, -1, -1):
                    if exc_simple in ctx[j] and not ctx[j].lstrip().startswith("at "):
                        return {"file": name, "exception_line": ctx[j].strip()[:400], "frame": ln.strip()}
    return None


etc = f"{cdir}/etc"
attempts = []
hit = None
plan = [cmd] * tries + ([canon] * 2 if canon and canon != cmd else []) if cmd else [canon] * tries
for k, run_cmd in enumerate(plan, 1):
    name = f"ca-val{SUF}-{case_id}"
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    start = time.time()
    dcmd = ["docker", "run", "--rm", "--name", name, "--hostname", "agent-host", "--network", "ca-internal",
            "--user", "20003:3160", "--cpus", "24", "--memory", "96g", "--shm-size", "4g",
            "--ulimit", "nofile=65536:65536", "--ulimit", "nproc=65536:65536",
            "-v", f"{val}:{val}", "-v", f"{val}/tmp:/tmp",
            "-v", f"{etc}/passwd:/etc/passwd:ro", "-v", f"{etc}/group:/etc/group:ro",
            "-v", f"{S}/jdk:/opt/tools/jdk:ro", "-v", f"{S}/apache-maven-3.9.15:/opt/tools/apache-maven-3.9.15:ro",
            "-v", f"{S}/apache-ant-1.10.14:/opt/tools/apache-ant-1.10.14:ro",
            # Old buggy versions (known bugs): JDK 8 and 7, Ant 1.9.16, protoc 2.5.0.
            "-v", f"{R}/tools/jdk8:/opt/tools/jdk8:ro", "-v", f"{S}/toolchain/jdk7:/opt/tools/jdk7:ro",
            "-v", f"{S}/toolchain/apache-ant-1.9.16:/opt/tools/apache-ant-1.9.16:ro",
            "-v", f"{S}/toolchain/protoc-2.5.0:/opt/tools/protoc-2.5.0:ro",
            "-e", f"HOME={val}/home", "-w", f"{val}/{tree}", "codingagent-runtime:1",
            "bash", "-c", f"source {val}/env.sh; {run_cmd}"]
    log = f"{cdir}/logs/validate{SUF}-{k}.log"
    with open(log, "w") as fo:
        try:
            rc = subprocess.run(dcmd, stdout=fo, stderr=subprocess.STDOUT, timeout=3 * 3600).returncode
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True); rc = "timeout"
    texts = [(log, open(log, errors="replace").read())]
    for f in glob.glob(f"{val}/{tree}/**/surefire-reports/*", recursive=True) + \
             glob.glob(f"{val}/{tree}/solr/build/**/test/*", recursive=True) + \
             glob.glob(f"{val}/{tree}/build/test/logs/*"):   # old ZooKeeper (Ant)
        if os.path.isfile(f) and os.path.getmtime(f) >= start - 5 and os.path.getsize(f) < 200_000_000:
            texts.append((f, open(f, errors="replace").read()))
    hit = search(texts)
    attempts.append({"n": k, "command": run_cmd, "rc": rc, "seconds": round(time.time() - start), "hit": hit})
    if hit:
        break
out["attempts"] = attempts
out["verdict"] = "REPRODUCED" if hit else "NOT_REPRODUCED"
save()
print(f"{case_id}: {out['verdict']}" + (f" ({len(prod)} production files changed, not carried over)" if prod else ""))
