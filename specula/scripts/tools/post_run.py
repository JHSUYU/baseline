#!/usr/bin/env python3
"""B6 after a run: verdict, leakage check, findings, and keeping a bug's TLC files.

Usage:
  post_run.py report <system> <case>                     # B6 steps 1-3 inputs: verdict, leakage, findings
  post_run.py keep <system> <case> <finding> [--verify]  # B6 step 6: copy files, write RERUN.md, rerun TLC

The run is the last "Run:" line of <system>/logs/<case>.log.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path("/bulk/specula-adhoc")
RUNS = Path("/users/ZhenyuLi/Specula/runs")
TLC = ROOT / "tlc"
JAVA = "/bulk/specula-adhoc/jdk/jdk-21.0.13+9/bin/java"
LEAK = r"/bulk/GraphChecker|/bulk/wt/|graphchecker|GraphChecker|Causynth|causynth|Causym|causym"


def work_dir(system: str, case: str) -> Path:
    log = (ROOT / system / "logs" / f"{case}.log").read_text(errors="replace")
    run = re.findall(r"^Run:\s+(\S+)", log, re.M)[-1]
    return RUNS / run / case / ".specula-output"


def report(system: str, case: str) -> None:
    w = work_dir(system, case)
    print(f"run: {w}")
    try:
        r = json.loads((w / "adhoc-result.json").read_text())
        print(f"adhoc-result: verdict={r.get('verdict')} mechanism={r.get('mechanism')} finding={r.get('finding')} "
              f"frame={r.get('stackFrame')}")
        for b in r.get("bounds", []):
            print(f"  bound {b}")
    except (OSError, json.JSONDecodeError) as e:
        print(f"adhoc-result: UNUSABLE ({e})")
    files = [str(p) for p in w.rglob("*") if p.is_file() and "/worktree/" not in str(p)
             and (p.name.endswith((".activity.jsonl", ".raw.json")) or re.match(r"turn.*\.log$", p.name))]
    hits = []
    for chunk in range(0, len(files), 200):
        out = subprocess.run(["grep", "-lE", LEAK, *files[chunk:chunk + 200]], capture_output=True, text=True).stdout
        hits += out.split()
    print(f"leakage: {len(files)} logs checked, {len(hits)} hits" + ("".join(f"\n  HIT {h}" for h in hits)))
    for v in sorted((w / "confirmation").glob("*/verdict.json")):
        try:
            d = json.loads(v.read_text())
        except json.JSONDecodeError:
            continue
        fid = v.parent.name
        title = ""
        issue = v.parent / "issue.json"
        if issue.is_file():
            try:
                title = json.loads(issue.read_text()).get("title", "")
            except json.JSONDecodeError:
                pass
        print(f"finding {fid}: {d.get('status')}  {title[:150]}")
    cb = w / "confirmed-bugs.md"
    if cb.is_file():
        nov = [l.strip() for l in cb.read_text(errors="replace").splitlines() if re.search(r"novelty|\bNEW\b", l, re.I)]
        print("novelty lines in confirmed-bugs.md:")
        for l in nov[:40]:
            print(f"  {l[:200]}")


def keep(system: str, case: str, fid: str, verify: bool) -> None:
    w = work_dir(system, case)
    dest = ROOT / system / "bugs" / case / fid
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("spec", "traces"):
        if (w / name).is_dir():
            shutil.copytree(w / name, dest / name, dirs_exist_ok=True, symlinks=True)
    for name in ("adhoc-result.json", "summary.md", "confirmed-bugs.md", "bug-severity.md", "modeling-brief.md"):
        if (w / name).is_file():
            shutil.copy2(w / name, dest / name)
    conf = w / "confirmation" / fid
    if conf.is_dir():
        shutil.copytree(conf, dest / "confirmation" / fid, dirs_exist_ok=True, symlinks=True,
                        ignore=shutil.ignore_patterns("worktree"))
        untracked = conf / "worktree-untracked.list"
        if untracked.is_file():
            for rel in untracked.read_text().split():
                src = conf / "worktree" / rel
                if src.is_file():
                    (dest / "reproduction" / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest / "reproduction" / rel)
    repro = w / "repro"
    if repro.is_dir():
        mine = re.compile(rf"(^|[^A-Za-z0-9]|bug){re.escape(fid)}($|[^0-9])")
        for p in repro.iterdir():
            if mine.search(p.name):
                (dest / "repro").mkdir(exist_ok=True)
                if p.is_dir():
                    shutil.copytree(p, dest / "repro" / p.name, dirs_exist_ok=True, symlinks=True)
                else:
                    shutil.copy2(p, dest / "repro" / p.name)
    # findings.json entry: config and counterexample
    cfg, cex = None, None
    try:
        fj = json.loads((w / "spec" / "findings.json").read_text())
        for f in (fj["findings"] if isinstance(fj, dict) else fj):
            if f.get("id") == fid:
                cfg, cex = f.get("config"), f.get("counterexample")
    except (OSError, json.JSONDecodeError, KeyError):
        pass
    # The counterexample may come from a variant config run from another directory with its own root
    # module (e.g. spec/output/hunt/gated/MCGuided1.tla + purge_guided_b.cfg): take both from the .out.
    run_dir, root_module = "spec", "MC.tla"
    if cex and (w / cex).is_file():
        head = (w / cex).read_text(errors="replace")[:20000]
        m = re.search(r"Parsing file (\S+/\.specula-output/(spec(?:/[^\s]*)?)/([A-Za-z0-9_]+\.tla))", head)
        if m:
            run_dir, root_module = m.group(2), m.group(3)
        stem = re.sub(r"(_bfs(_w\d+)?|_sim|_dfs)?\.out$", "", Path(cex).name)
        if not (w / run_dir / str(cfg)).is_file() or run_dir != "spec":
            # the config named like the log, with or without the MC_hunt_ prefix
            for name in (f"{stem}.cfg", f"MC_hunt_{stem}.cfg"):
                if (w / run_dir / name).is_file():
                    cfg = name
                    break
    tlc_line = jdk_line = "?"
    if cex and (w / cex).is_file():
        lines = (w / cex).read_text(errors="replace").splitlines()
        tlc_line = lines[0] if lines else "?"
        m = re.search(r"Eclipse Adoptium ([\d.]+)", " ".join(lines[:3]))
        jdk_line = m.group(1) if m else "?"
    inv = "TargetSafe"
    if cex and (w / cex).is_file():
        m = re.search(r"Invariant (\w+) is violated", (w / cex).read_text(errors="replace"))
        inv = m.group(1) if m else inv
    if not cfg:
        (dest / "RERUN.md").write_text(f"""# Rerun {case} {fid}

{fid} has no TLC config or counterexample of its own (a code-review finding). The run's `spec/` is kept for
reference. Reproduce it from `confirmation/{fid}/` (verdict, investigation, issue, instrumentation patch), the
test files in `reproduction/` (from `worktree-untracked.list`, if any) and `repro/`.
""")
        print(f"kept {dest} (code-review finding: no TLC counterexample)")
        return
    ttrace = sorted(p.name for p in (dest / "spec").glob("*_TTrace_*.tla")) if (dest / "spec").is_dir() else []
    cmd = (f"cd {dest}/{run_dir}\n"
           f"java -XX:+UseParallelGC -cp {TLC}/tla2tools.jar:{TLC}/CommunityModules-deps.jar \\\n"
           f"  tlc2.TLC -workers 1 -metadir /tmp/rerun-{case}-{fid}/states -config {cfg} {root_module}")
    (dest / "RERUN.md").write_text(f"""# Rerun {case} {fid}

- Config: `{run_dir}/{cfg}` (root module `{root_module}`); counterexample log: `{cex}` (from `spec/findings.json` and the log's own header).
- TLC: `{tlc_line}`; JDK {jdk_line} (`/bulk/specula-adhoc/jdk/jdk-21.0.13+9`). Jars pinned in `{TLC}` (`SHA256SUMS`).
- Expect TLC to report: `Invariant {inv} is violated`. State counts may differ from the log when the worker count differs.

```
{cmd}
```

Read the trace in the `.out` log, or open a trace explorer: {', '.join(f'`spec/{t}`' for t in ttrace) or 'none kept'}.
Reproduction: `confirmation/{fid}/` (verdict, investigation, issue, instrumentation patch), the test files in `reproduction/` (from `worktree-untracked.list`), and `repro/`.
""")
    print(f"kept {dest} ({sum(p.stat().st_size for p in dest.rglob('*') if p.is_file()) // 1024} KB); cfg={cfg} cex={cex}")
    if verify and cfg:
        meta = Path(f"/tmp/rerun-{case}-{fid}")
        shutil.rmtree(meta, ignore_errors=True)
        out = subprocess.run(["timeout", "7200", JAVA, "-XX:+UseParallelGC", "-cp",
                              f"{TLC}/tla2tools.jar:{TLC}/CommunityModules-deps.jar", "tlc2.TLC", "-workers", "4",
                              "-metadir", str(meta / "states"), "-config", cfg, root_module],
                             cwd=dest / run_dir, capture_output=True, text=True).stdout
        shutil.rmtree(meta, ignore_errors=True)
        viol = re.findall(r"Invariant \w+ is violated", out)
        states = re.findall(r"(\d[\d,]*) distinct states found", out)
        line = f"rerun (4 workers): {viol[0] if viol else 'NO VIOLATION'}; distinct states {states[-1] if states else '?'}"
        print(line)
        with open(dest / "RERUN.md", "a") as f:
            f.write(f"\nChecked {subprocess.run(['date', '-u', '+%Y-%m-%d'], capture_output=True, text=True).stdout.strip()}: {line}.\n")


if __name__ == "__main__":
    if sys.argv[1] == "report":
        report(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "keep":
        keep(sys.argv[2], sys.argv[3], sys.argv[4], "--verify" in sys.argv)
    else:
        sys.exit(__doc__)
