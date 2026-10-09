#!/usr/bin/env python3
"""Apply identical research hooks to the two pristine SOLR-16257 revisions.

Writes a separate overlay source tree; the official source exports stay intact.
Every anchor must occur exactly once or the build stops.
"""

from pathlib import Path
import argparse
import hashlib
import json
import re


ROOT = Path("/users/ZhenyuLi/baseline/crashfuzz/cases/SOLR-09/actor-v2/solr16257-diff")


def replace_once(source: str, before: str, after: str, label: str) -> str:
    count = source.count(before)
    if count != 1:
        raise ValueError(f"{label}: expected one anchor, got {count}")
    return source.replace(before, after)


def regex_once(source: str, pattern: str, suffix: str, label: str) -> str:
    updated, count = re.subn(pattern, lambda match: match.group(0) + suffix, source)
    if count != 1:
        raise ValueError(f"{label}: expected one method, got {count}")
    return updated


def transform(relative: str, source: str) -> str:
    if relative.endswith("DeleteReplicaCmd.java"):
        marker = "    boolean isLive =\n"
        hook = (
            "    baseline.solr09.FeedbackProbe.bindTargetReader(\n"
            "        ccc.getZkStateReader().getZkClient(),\n"
            "        ccc.getCoreContainer().getZkController().getNodeName(),\n"
            "        replica.getNodeName(), core);\n"
        )
        source = replace_once(source, marker, hook + marker, "bind target")
        before = "        if (!callable.call())\n          throw new SolrException(\n"
        after = (
            "        boolean coreNodeGone = callable.call();\n"
            "        baseline.solr09.FeedbackProbe.targetCheck(\n"
            "            !coreNodeGone, coll.getName(), shardId, replicaName, core, isLive,\n"
            "            ccc.getZkStateReader().getZkClient(),\n"
            "            ccc.getCoreContainer().getZkController().getNodeName());\n"
            "        if (!coreNodeGone)\n          throw new SolrException(\n"
        )
        return replace_once(source, before, after, "selected guard")

    if relative.endswith("HttpShardHandler.java"):
        marker = "    // all variables that set inside this listener must be at least volatile\n"
        hook = (
            "    // Model a transport IOException immediately before the selected HTTP POST.\n"
            "    if (baseline.solr09.FeedbackProbe.httpFailure(\n"
            "        params.get(\"qt\"), params.get(\"action\"), params.get(\"core\"),\n"
            "        sreq.nodeName, shard)) {\n"
            "      srsp.setException(new java.io.IOException(\"Injected selected CoreAdmin HTTP I/O failure\"));\n"
            "      responses.add(srsp);\n"
            "      return;\n"
            "    }\n\n"
        )
        return replace_once(source, marker, hook + marker, "HTTP submit")

    if relative.endswith("SolrZkClient.java"):
        source = regex_once(
            source,
            r"public List<String> getChildren\(\s*final String path, final Watcher watcher, Stat stat, boolean retryOnConnLoss\)\s*throws KeeperException, InterruptedException \{",
            '\n    baseline.solr09.FeedbackProbe.io("GET_CHILDREN_STAT", path, this);',
            "ZK getChildren+stat",
        )
        source = regex_once(
            source,
            r"public byte\[\] getData\(\s*final String path, final Watcher watcher, final Stat stat, boolean retryOnConnLoss\)\s*throws KeeperException, InterruptedException \{",
            '\n    baseline.solr09.FeedbackProbe.io("GET_DATA", path, this);',
            "ZK getData",
        )
        return source

    if relative.endswith("ZkController.java"):
        marker = "    checkNoOldClusterstate(zkClient);\n"
        hook = "    baseline.solr09.FeedbackProbe.registerNode(zkClient, nodeName);\n"
        return replace_once(source, marker, hook + marker, "node registration")

    if relative.endswith("ZkStateReader.java"):
        before = (
            "      if (!latch.await(wait, unit))\n"
            "        throw new TimeoutException(\n"
            "            \"Timeout waiting to see state for collection=\"\n"
            "                + collection\n"
            "                + \" :\"\n"
            "                + docCollection.get());\n"
            "      return docCollection.get();"
        )
        after = (
            "      if (!latch.await(wait, unit)) {\n"
            "        baseline.solr09.FeedbackProbe.preTimeoutState(this, collection);\n"
            "        throw new TimeoutException(\n"
            "            \"Timeout waiting to see state for collection=\"\n"
            "                + collection\n"
            "                + \" :\"\n"
            "                + docCollection.get());\n"
            "      }\n"
            "      return docCollection.get();"
        )
        return replace_once(source, before, after, "predicate wait timeout")

    raise ValueError(f"no transform for {relative}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("version", choices=["parent", "fix"])
    args = parser.parse_args()
    source_root = ROOT / f"{args.version}-source"
    overlay_root = ROOT / f"{args.version}-overlay-src"
    paths = [
        "solr/core/src/java/org/apache/solr/cloud/api/collections/DeleteReplicaCmd.java",
        "solr/core/src/java/org/apache/solr/handler/component/HttpShardHandler.java",
        "solr/solrj/src/java/org/apache/solr/common/cloud/SolrZkClient.java",
        "solr/core/src/java/org/apache/solr/cloud/ZkController.java",
        "solr/solrj/src/java/org/apache/solr/common/cloud/ZkStateReader.java",
    ]
    receipt = {"version": args.version, "files": {}}
    for relative in paths:
        original = (source_root / relative).read_text()
        modified = transform(relative, original)
        target = overlay_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(modified)
        receipt["files"][relative] = {
            "pristine_sha256": hashlib.sha256(original.encode()).hexdigest(),
            "overlay_sha256": hashlib.sha256(modified.encode()).hexdigest(),
        }
    receipt_path = ROOT / f"{args.version}-overlay-receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(receipt_path)


if __name__ == "__main__":
    main()
