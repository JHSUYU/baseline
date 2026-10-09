#!/usr/bin/env python3
"""Compile case-local hooks into clean Solr 8.11.4 source copies."""

from pathlib import Path
import subprocess


CASE = Path(__file__).resolve().parents[1]
ROOT = CASE / "solr-source"
OUT = CASE / "probe/generated"
RELATIVE = (
    "solr/solrj/src/java/org/apache/solr/client/solrj/impl/"
    "BaseHttpClusterStateProvider.java"
)


def replace_once(source: str, before: str, after: str) -> str:
    count = source.count(before)
    if count != 1:
        raise RuntimeError(f"Expected one source location, found {count}: {before!r}")
    return source.replace(before, after)


def main() -> None:
    source = (ROOT / RELATIVE).read_text()
    source = replace_once(
        source,
        "  private Map<String, List<String>> getAliases(boolean forceFetch) {\n",
        "  private Map<String, List<String>> getAliases(boolean forceFetch) {\n"
        "    baseline.solr01.FeedbackProbe.begin(forceFetch, String.valueOf(liveNodes));\n",
    )
    source = replace_once(
        source,
        "          CollectionAdminResponse response = new CollectionAdminRequest.ListAliases().process(client);",
        "          baseline.solr01.FeedbackProbe.io(baseUrl);\n"
        "          CollectionAdminResponse response = new CollectionAdminRequest.ListAliases().process(client);",
    )
    source = replace_once(
        source,
        "          this.aliasesTimestamp = System.nanoTime();\n"
        "          return Collections.unmodifiableMap(this.aliases);",
        "          this.aliasesTimestamp = System.nanoTime();\n"
        "          baseline.solr01.FeedbackProbe.targetCheck(false, baseUrl);\n"
        "          return Collections.unmodifiableMap(this.aliases);",
    )
    source = replace_once(
        source,
        "      throw new RuntimeException(\"Tried fetching aliases using all the node names we knew of, i.e. \" + liveNodes +\". However, \"",
        "      baseline.solr01.FeedbackProbe.targetCheck(true, String.valueOf(liveNodes));\n"
        "      throw new RuntimeException(\"Tried fetching aliases using all the node names we knew of, i.e. \" + liveNodes +\". However, \"",
    )
    source = replace_once(
        source,
        "    } else {\n      return Collections.unmodifiableMap(this.aliases); // cached copy is fresh enough",
        "    } else {\n"
        "      baseline.solr01.FeedbackProbe.targetCheck(false, \"cached aliases\");\n"
        "      return Collections.unmodifiableMap(this.aliases); // cached copy is fresh enough",
    )
    output = OUT / RELATIVE
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(source)
    cp = (CASE / "classpath.txt").read_text().strip()
    subprocess.run([
        "/usr/lib/jvm/java-8-openjdk-amd64/bin/javac", "-source", "8", "-target", "8",
        "-implicit:none", "-sourcepath", "", "-cp", cp, "-d", str(CASE / "classes"),
        str(CASE / "probe/FeedbackProbe.java"), str(output),
    ], check=True)


if __name__ == "__main__":
    main()
