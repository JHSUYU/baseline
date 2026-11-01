#!/usr/bin/env python3
"""Insert one stderr probe line at the entry of each check method (B3 reach probe; scratch trees only).

Usage: insert_probes.py <tree> <inventory.tsv>
For each inventory row: find the method by name in the upstream file, scanning back from the
check line to the nearest declaration of that name, and print SPECULA-PROBE <case> on entry.
"""
import csv, re, sys
from collections import defaultdict
from pathlib import Path

tree, inv = Path(sys.argv[1]), sys.argv[2]
by_file = defaultdict(list)
for row in csv.DictReader(open(inv), delimiter="\t"):
    path, line = row["site_upstream"].rsplit(":", 1)
    name = row["method"].split("(")[0].split(".")[-1]
    by_file[path].append((row["case"], int(line), name))

for path, checks in by_file.items():
    f = tree / path
    lines = f.read_text().splitlines(keepends=True)
    inserts = defaultdict(list)  # line index after which to insert -> cases
    for case, line, name in checks:
        k = line - 1
        pat = re.compile(r"\b" + re.escape(name) + r"\s*\(")
        while k >= 0:
            l = lines[k]
            if pat.search(l) and not l.strip().startswith(("return", "if", "//", "*")) and "=" not in l.split(name)[0] \
                    and not re.search(r"\.\s*" + re.escape(name), l) and not l.rstrip().endswith(";"):
                break
            k -= 1
        assert k >= 0, (case, path, name)
        j = k
        while "{" not in lines[j]:
            j += 1
        inserts[j].append(case)
        print(f"{case}: {path}:{k + 1} {lines[k].strip()[:90]} -> probe after line {j + 1}")
    for j in sorted(inserts, reverse=True):
        cases = " ".join(sorted(set(inserts[j])))
        lines.insert(j + 1, f'    System.err.println("SPECULA-PROBE {cases}");\n')
    f.write_text("".join(lines))
