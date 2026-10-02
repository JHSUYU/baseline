"""Verify sampled source sites against the pinned Hadoop 3.4.3 bytecode."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess


HERE = Path(__file__).resolve().parent
HADOOP = Path.home() / ".baseline-deps/hadoop-3.4.3/share/hadoop/hdfs"
CLASSPATH = ":".join(str(HADOOP / name) for name in (
    "hadoop-hdfs-3.4.3.jar", "hadoop-hdfs-client-3.4.3.jar"))
SECTION = re.compile(r"(?=^  [^\n]+;\n    descriptor: )", re.MULTILINE)
HEADER = re.compile(r"(?m)^  ([^\n]+);\n    descriptor: ([^\n]+)")
ATHROW = re.compile(r"(?m)^\s+(\d+): athrow\b")
LINE = re.compile(r"(?m)^\s+line (\d+): (\d+)")


def throws_in_method(row: dict, text: str) -> list[dict]:
    method = row["agent_method"].split("#", 1)[1].split("(", 1)[0]
    descriptor = row["agent_method"].split("#", 1)[1].split(method, 1)[1]
    results = []
    matches = 0
    for section in SECTION.split(text):
        header = HEADER.search(section)
        if header is None or header.group(2) != descriptor:
            continue
        declaration = header.group(1)
        if method == "<init>":
            if row["class"].split(".")[-1].split("$")[-1] not in declaration:
                continue
        elif re.search(r"\b" + re.escape(method) + r"\(", declaration) is None:
            continue
        matches += 1
        lines = [(int(pc), int(source)) for source, pc in LINE.findall(section)]
        for pc in map(int, ATHROW.findall(section)):
            preceding = [(start, source) for start, source in lines
                         if start <= pc]
            source = max(preceding, default=(None, None))[1]
            results.append({"bytecode_offset": pc, "source_line": source})
    if matches != 1:
        raise RuntimeError("expected exactly one compiled method for "
                           + row["agent_method"] + ", found " + str(matches))
    return results


def main() -> None:
    selection = json.loads((HERE / "selected10.json").read_text())
    cache = {}
    rows = []
    for row in selection["sites"]:
        cls = row["class"]
        if cls not in cache:
            command = ["javap", "-classpath", CLASSPATH,
                       "-c", "-l", "-s", "-p", cls]
            result = subprocess.run(command, capture_output=True, text=True,
                                    timeout=60, check=True)
            cache[cls] = result.stdout
        throws = throws_in_method(row, cache[cls])
        at_line = [item for item in throws
                   if item["source_line"] == row["line"]]
        nearby = sorted((item for item in throws
                         if item["source_line"] is not None and
                         abs(item["source_line"] - row["line"]) <= 3),
                        key=lambda item: abs(item["source_line"] - row["line"]))
        if row["site_kind"] == "check":
            selected = None
            status = "precondition_call_requires_separate_oracle"
        elif len(at_line) == 1:
            selected = at_line[0]
            status = "exact_source_line"
        elif not at_line and len(nearby) == 1:
            selected = nearby[0]
            status = "unique_nearby_athrow"
        else:
            selected = None
            status = "ambiguous_or_missing_athrow"
        rows.append({**row, "bytecode_status": status,
                     "compiled_throws": throws,
                     "compiled_target_throw": (None if selected is None else
                                               row["agent_method"] + "#L"
                                               + str(selected["source_line"]))})
        print("{:02d} {:32s} {}".format(row["draw"], status,
                                         rows[-1]["compiled_target_throw"]))
    output = {k: v for k, v in selection.items() if k != "sites"}
    output["sites"] = rows
    (HERE / "mapped10.json").write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
