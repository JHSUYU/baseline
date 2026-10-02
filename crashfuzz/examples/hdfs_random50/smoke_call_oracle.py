"""Exercise selected-call instrumentation on a real Java exception path."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile


HERE = Path(__file__).resolve().parent
AGENT = HERE.parents[1] / "agent/target/adhoc-crashfuzz-agent-0.1.0.jar"
SOURCE = """public class CallOracleFixture {
  static void run(boolean good) {
    java.util.Objects.requireNonNull(good ? "ok" : null);
  }
  public static void main(String[] args) {
    try { run(args[0].equals("good")); }
    catch (NullPointerException expected) { }
  }
}
"""


def main() -> None:
    line = next(number for number, text in enumerate(SOURCE.splitlines(), 1)
                if "requireNonNull" in text)
    site = ("CallOracleFixture#run(Z)V#L" + str(line)
            + "->java/util/Objects#requireNonNull")
    with tempfile.TemporaryDirectory(prefix="adhoc-call-oracle-") as root:
        directory = Path(root)
        source = directory / "CallOracleFixture.java"
        source.write_text(SOURCE)
        subprocess.run(["javac", str(source)], check=True)
        config = directory / "agent.properties"
        for label, expected in (("good", False), ("bad", True)):
            traces = directory / label
            traces.mkdir()
            config.write_text("\n".join([
                "node.id=smoke", "trace.dir=" + str(traces),
                "include.classes=CallOracleFixture",
                "method.rules=CallOracleFixture#run",
                "trace.fields=false", "trace.branches=false",
                "target.call=" + site,
                "target.exception=java.lang.NullPointerException", "",
            ]))
            subprocess.run(["java", "-javaagent:" + str(AGENT) + "="
                            + str(config), "-cp", str(directory),
                            "CallOracleFixture", label], check=True,
                           capture_output=True, text=True)
            targets = []
            for path in traces.glob("trace-*.jsonl"):
                targets.extend(json.loads(line) for line in path.read_text().splitlines()
                               if json.loads(line).get("kind") == "TARGET")
            if not targets or {row["site"] for row in targets} != {site}:
                raise AssertionError("selected call did not emit its target site")
            fatal = any(row.get("fatal", False) for row in targets)
            if fatal != expected:
                raise AssertionError(label + " fatal=" + str(fatal))
    print("selected-call healthy and exceptional paths passed")


if __name__ == "__main__":
    main()
