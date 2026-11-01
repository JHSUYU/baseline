#!/usr/bin/env python3
"""Locate each check's marked throw in the GraphChecker fork and the same statement upstream.

Usage: find_sites.py <fork tree> <upstream tree> <id>[=<marker>] ...
Maps the fork's marker line to the upstream file with a line diff (difflib), and prints the
fork's marked statement and the upstream context around the mapped line, so the operator can
read the upstream throw line, method, thrown type and guard.  Operator-only: its output never
goes to a Specula agent.
"""
import difflib, re, subprocess, sys
from pathlib import Path

fork, up = Path(sys.argv[1]), Path(sys.argv[2])

def map_line(a, b, i):
    """Map 0-based line i of a to b: exact for equal blocks, else the nearest replaced block's start."""
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if i1 <= i < i2:
            return j1 + (i - i1) if tag == "equal" else j1
    return None

for arg in sys.argv[3:]:
    cid, _, marker = arg.partition("=")
    marker = marker or cid
    hits = subprocess.run(["grep", "-rn", "--include=*.java", f'CausynthExceptionTarget("{marker}")', str(fork)],
                          capture_output=True, text=True).stdout.strip().splitlines()
    hits = [h for h in hits if "import " not in h]
    print(f"===== {cid} (marker {marker}): {len(hits)} marker(s)")
    for h in hits:
        path, line, _ = h.split(":", 2)
        rel = Path(path).relative_to(fork)
        a = Path(path).read_text(errors="replace").splitlines()
        i = int(line) - 1
        print(f"fork {rel}:{line}")
        for n in range(max(0, i - 6), min(i + 3, len(a))):
            print(f"  F{n + 1:5d}| {a[n]}")
        upath = up / rel
        if not upath.is_file():
            print("  upstream file missing"); continue
        b = upath.read_text(errors="replace").splitlines()
        j = map_line(a, b, i)
        print(f"  upstream mapped line: {None if j is None else j + 1}")
        if j is not None:
            for n in range(max(0, j - 8), min(j + 4, len(b))):
                print(f"  U{n + 1:5d}| {b[n]}")
