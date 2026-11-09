#!/usr/bin/env python3
"""Build specula/new-bugs and specula/known-bugs in the baseline clone from verified-bugs/ and known-bugs/.

Per bug folder: BUG.md (explanation, cost), tlc/ (modules, config, counterexample log, RERUN.md),
repro/ (reproduction tests and scripts, small logs), confirmation/ (issue.json, verdict.json, debate.md, investigation.md).
"""
import json, re, shutil, csv
from pathlib import Path

R = Path("/bulk/specula-adhoc")
OUT = R / "publish/baseline/specula"
TRUTH = Path("/users/ZhenyuLi/bugstudy/truth")
MAXF = 1_000_000
TEXT = (".java", ".sh", ".py", ".patch", ".diff", ".md", ".txt", ".log", ".out", ".json", ".list", ".xml", ".properties", ".cfg", ".tla", ".yaml")


def rerun_info(src):
    t = (src / "RERUN.md").read_text()
    cd = re.search(r"^cd (\S+)", t, re.M)
    if not cd:
        return None
    m = re.search(r"-config (\S+) (\S+\.tla)", t)
    cex = re.search(r"counterexample log: `([^`]+)`", t)
    inv = re.search(r"Expect TLC to report: `([^`]+)`", t)
    chk = re.search(r"^Checked .*$", t, re.M)
    return dict(dir=Path(cd[1]), cfg=m[1], root=m[2], cex=src / cex[1] if cex else None,
                expect=inv[1] if inv else "Invariant TargetSafe is violated", checked=chk[0] if chk else "")


def copy_tlc(src, dst, name):
    info = rerun_info(src)
    if not info:
        return None
    d = dst / "tlc"; d.mkdir(parents=True)
    run = info["dir"]
    spec = src / "spec"
    # modules: those in the run directory, plus spec/ top level ones not shadowed
    for p in sorted(run.glob("*.tla")):
        if "TTrace" not in p.name:
            shutil.copy2(p, d / p.name)
    if run != spec:
        for p in sorted(spec.glob("*.tla")):
            if "TTrace" not in p.name and not (d / p.name).exists():
                shutil.copy2(p, d / p.name)
    shutil.copy2(run / info["cfg"], d / info["cfg"])
    cexname = ""
    if info["cex"] and info["cex"].exists():
        cexname = "counterexample-" + info["cex"].name
        shutil.copy2(info["cex"], d / cexname)
    jars = "../../../data/tlc"
    (d / "RERUN.md").write_text(f"""# {name}: rerun the TLC counterexample

Files: the specification modules (`*.tla`), the config that produced the counterexample (`{info['cfg']}`, root module `{info['root']}`), and the counterexample log (`{cexname}`). TLC `2026.10.24.013619 (rev: 2ef2af8)` on JDK 21; the jars are pinned in `{jars}/` (`SHA256SUMS`).

```
cd {d.relative_to(OUT)}   # from specula/
java -XX:+UseParallelGC -cp {jars}/tla2tools.jar:{jars}/CommunityModules-deps.jar \\
  tlc2.TLC -workers 4 -metadir /tmp/tlc-{name} -config {info['cfg']} {info['root']}
```

TLC must report `{info['expect']}`. State counts can differ from the log when the worker count differs.
""")
    return dict(cfg=info["cfg"], root=info["root"], expect=info["expect"], cex=cexname)


def copy_small(srcdir, dstdir):
    n = 0
    if not srcdir.exists():
        return 0
    for p in srcdir.rglob("*"):
        if p.is_file() and not p.is_symlink() and p.stat().st_size <= MAXF and p.suffix in TEXT and "/worktree/" not in str(p):
            q = dstdir / p.relative_to(srcdir); q.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(p, q); n += 1
    return n


def copy_common(src, dst, f):
    c = src / "confirmation" / f
    (dst / "confirmation").mkdir(parents=True)
    for x in ("issue.json", "verdict.json", "debate.md", "investigation.md", "confirmation.md"):
        if (c / x).exists() and (c / x).stat().st_size <= MAXF:
            shutil.copy2(c / x, dst / "confirmation" / x)
    copy_small(src / "repro", dst / "repro")
    copy_small(src / "reproduction", dst / "repro" / "reproduction")
    for x in ("adhoc-result.json",):
        if (src / x).exists():
            shutil.copy2(src / x, dst / x)


def issue_lines(src, f):
    p = src / "confirmation" / f / "issue.json"
    if not p.exists():
        return ""
    d = json.load(open(p))
    out = [f"**Specula's finding {f}:** {d.get('title','')}", ""]
    for k in ("cause", "trigger", "consequence"):
        if d.get(k):
            out.append(f"- **{k.capitalize()}:** {d[k]}")
    if d.get("premises"):
        out.append("- **Premises:** " + " ".join(d["premises"]))
    return "\n".join(out)


def verified_row(system, case, f):
    lines = (R / system / "VERIFIED-BUGS.md").read_text().splitlines()
    pats = [f"{case}/{f}"]
    for i, l in enumerate(lines):
        if l.startswith("|") and any(re.search(re.escape(p) + r"\b", l) for p in pats):
            j = i
            while j > 0 and not re.match(r"^\|\s*-{3}", lines[j]):
                j -= 1
            head = [h.strip() for h in lines[j - 1].strip("|").split("|")]
            cells = [c.strip() for c in l.strip().strip("|").split("|")]
            return "\n".join(f"- **{h}:** {c}" for h, c in zip(head, cells) if h and h != "#")
    return ""


def section(text, title):
    m = re.search(r"^## " + title + r"[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m[1].strip() if m else ""


def new_bugs():
    D = OUT / "new-bugs"
    if D.exists(): shutil.rmtree(D)
    D.mkdir()
    rows = json.load(open(R / "verified-bugs/bugs.json"))
    res = {}
    for l in open(R / "verified-bugs/rerun-results.tsv"):
        a = l.rstrip("\n").split("\t"); res[a[0]] = a[1]
    for r in rows:
        src = R / "verified-bugs" / r["dir"]; dst = D / r["dir"]; dst.mkdir()
        tlc = copy_tlc(src, dst, r["dir"]); copy_common(src, dst, r["finding"])
        r["tlc_rerun"] = res.get(r["dir"], "")
        (dst / "BUG.md").write_text(f"""# {r['case']} {r['finding']} (tier {r['tier']}): {r['bug']}

System: {r['system']}. Found by Specula's ad hoc run `{r['case']}`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator).{(' Same defect as ' + r['same_as'] + '.') if r['same_as'] else ''}

## Explanation (verified)

{verified_row(r['system'], r['case'], r['finding'])}

{issue_lines(src, r['finding'])}

## Evidence

- TLC: {'`tlc/RERUN.md` (config `' + tlc['cfg'] + '`, expect `' + tlc['expect'] + '`); rerun 2026-11-07: ' + r['tlc_rerun'] if tlc else 'none (code-review finding); the evidence is the reproduction'}.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `{r['case']}` (all phases) | {r['case_time']} | {r['case_tokens']} | {r['case_cost']} |
| of which: confirming this finding | | {r['confirm_tokens']} | {r['confirm_cost']} |

Time is active time; quota sleeps are excluded.
""")
    json.dump(rows, open(D / "bugs.json", "w"), indent=1)
    return rows


def known_bugs():
    D = OUT / "known-bugs"
    if D.exists(): shutil.rmtree(D)
    D.mkdir()
    rows = json.load(open(R / "known-bugs/bugs.json"))
    res = {}
    for l in open(R / "known-bugs/rerun-results.tsv"):
        a = l.rstrip("\n").split("\t"); res[a[0]] = a[1]
    for r in rows:
        truth = (TRUTH / f"{r['case']}.md").read_text()
        r["mechanism"] = section(truth, "Mechanism"); r["expected"] = section(truth, "Expected detection")
        r["tlc_rerun"] = res.get(r["dir"], "")
        if not r["dir"]:
            continue
        src = R / "known-bugs" / r["dir"]; dst = D / r["dir"]; dst.mkdir()
        tlc = copy_tlc(src, dst, r["dir"]); copy_common(src, dst, r["finding"])
        (dst / "BUG.md").write_text(f"""# {r['jira']}: detected by Specula ({r['detected']}), finding {r['finding']}

Specula ran on the bug's buggy version (the parent of its fix commit) as ad hoc case `{r['case']}`, with no access to the fix, the JIRA or the git history.

## The known bug (from the JIRA and the fix)

{r['mechanism']}

## What counted as detecting it (written before the run)

{r['expected']}

## What Specula found

{issue_lines(src, r['finding'])}

**Operator's judgement:** {r['detected']}. {r['note']}

## Evidence

- TLC: {'`tlc/RERUN.md` (config `' + tlc['cfg'] + '`, expect `' + tlc['expect'] + '`); rerun 2026-11-08: ' + r['tlc_rerun'] if tlc else 'none (code-review finding); the evidence is the reproduction'}.
- Reproduction on the buggy version: `repro/` and `confirmation/` (Specula's verdict, investigation, issue).

## Cost of the run (all phases)

| time | tokens | cost |
| ---: | ---: | ---: |
| {r['time']} | {r['tokens']} | {r['cost']} |

Time is active time; quota sleeps are excluded.
""")
    json.dump(rows, open(D / "bugs.json", "w"), indent=1)
    return rows


if __name__ == "__main__":
    print(len(new_bugs()), len(known_bugs()))
