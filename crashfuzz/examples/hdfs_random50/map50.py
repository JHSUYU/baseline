"""Resolve each sampled site to its HDFS 3.4.3 bytecode throw instruction."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
TEN = HERE.parent / "hdfs_random10"
sys.path.insert(0, str(TEN))
from map_bytecode import CLASSPATH, throws_in_method  # noqa: E402


PRECONDITIONS = {
    13: ("checkArgument", "java.lang.IllegalArgumentException"),
    15: ("checkNotNull", "java.lang.NullPointerException"),
    19: ("checkState", "java.lang.IllegalStateException"),
    26: ("checkArgument", "java.lang.IllegalArgumentException"),
    33: ("checkState", "java.lang.IllegalStateException"),
    50: ("checkState", "java.lang.IllegalStateException"),
}


def main() -> None:
    selection = json.loads((HERE / "selected50.json").read_text())
    first = json.loads((TEN / "mapped10.json").read_text())
    cache = {}
    mapped = [dict(site) for site in first["sites"]]
    for site in selection["sites"][10:]:
        row = dict(site)
        cls = row["class"]
        try:
            if cls not in cache:
                result = subprocess.run([
                    "javap", "-classpath", CLASSPATH, "-c", "-l", "-s",
                    "-p", cls], capture_output=True, text=True,
                    timeout=60, check=True)
                cache[cls] = result.stdout
            throws = throws_in_method(row, cache[cls])
            at_line = [item for item in throws
                       if item["source_line"] == row["line"]]
            nearby = sorted((item for item in throws
                             if item["source_line"] is not None
                             and abs(item["source_line"] - row["line"]) <= 3),
                            key=lambda item: abs(item["source_line"] - row["line"]))
            if row["draw"] in PRECONDITIONS:
                chosen = None
                check, exception = PRECONDITIONS[row["draw"]]
                call = (row["agent_method"] + "#L" + str(row["line"])
                        + "->org/apache/hadoop/util/Preconditions#" + check)
                status = "exact_precondition_call"
                row["compiled_target_call"] = call
                row["target_exception"] = exception
            elif row["site_kind"] == "check":
                chosen = None
                status = "callee_precondition_needs_oracle"
            elif len(at_line) == 1:
                chosen = at_line[0]
                status = "exact_source_line"
            elif not at_line and len(nearby) == 1:
                chosen = nearby[0]
                status = "unique_nearby_athrow"
            elif row["draw"] == 40:
                # javac duplicates this InterruptedIOException throw across
                # synchronized/finally exits; all copies retain line 1110.
                copies = [item for item in throws
                          if item["source_line"] == 1110]
                if len(copies) != 3:
                    raise RuntimeError("BlockReceiver throw copies changed")
                chosen = copies[0]
                status = "three_compiler_copies_same_line"
            else:
                chosen = None
                status = "ambiguous_or_missing_athrow"
            row.update({
                "bytecode_status": status,
                "compiled_throws": throws,
                "compiled_target_throw": (None if chosen is None else
                                          row["agent_method"] + "#L" +
                                          str(chosen["source_line"])),
            })
        except (subprocess.CalledProcessError, RuntimeError) as error:
            row.update({"bytecode_status": "mapping_error",
                        "mapping_error": str(error),
                        "compiled_throws": [],
                        "compiled_target_throw": None})
        mapped.append(row)
        print("{:02d} {:36s} {}".format(
            row["draw"], row["bytecode_status"],
            row["compiled_target_throw"]), flush=True)
    result = {key: value for key, value in selection.items() if key != "sites"}
    result["sites"] = mapped
    (HERE / "mapped50.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
