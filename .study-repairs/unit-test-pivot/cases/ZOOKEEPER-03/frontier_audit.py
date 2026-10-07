#!/usr/bin/env python3
"""Read-only, archive-backed audit of ZK03's remaining observed-I/O frontier."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile


HERE = Path(__file__).resolve().parent
PIVOT = HERE.parents[1]
REPO = PIVOT.parents[1]
CHECK = "SessionTrackerImpl#setOwner:329:missingOrClosing"
SOURCE_REVISION = "9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae"
LEGACY_COMMIT = "62e1a115c4c225c90605e1c4c540983591d0f903"
MULTIOP_COMMIT = "940bff2411da9112d2102d8652fcdba843456725"
SOURCES = {
    "pre_io": (
        "zk-actor-v2/cases/ZOOKEEPER-03/evidence/raw-runs.tar.gz",
        LEGACY_COMMIT,
        "caf826bc7ba3fde07e6770dbf54cfed9bf1e4e2992d9a882a605ee65eab5d686",
    ),
    "post_response": (
        "zk-actor-v2/cases/ZOOKEEPER-03/after-response/evidence/raw-runs.tar.gz",
        LEGACY_COMMIT,
        "a77d70aed657e1b35b4d3ee6536a13cc4dbbd92fed9281c9747805e344aac3bc",
    ),
    "multiop_pilot": (
        "cases/ZOOKEEPER-03/multiop-extension/evidence/raw-pilot.tar.gz",
        MULTIOP_COMMIT,
        "d74f2be2a959cea03fc51dd3b626761aba92bfa76d99ab68a6a119cd65e9d63b",
    ),
    "multiop_campaign": (
        "cases/ZOOKEEPER-03/multiop-extension/evidence/raw-campaign.tar.gz",
        MULTIOP_COMMIT,
        "bebb74aee76a6a65db6e1e0c8752c87001d60186b9fb815474c9d81bc3eb4df3",
    ),
}


def open_archive(label):
    rel, commit, expected = SOURCES[label]
    path = PIVOT / rel
    if path.is_file():
        data = path.read_bytes()
    else:
        repo_rel = str(path.relative_to(REPO))
        data = subprocess.check_output(
            ["git", "-C", str(REPO), "show", commit + ":" + repo_rel]
        )
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected:
        raise RuntimeError(f"{label}: archive SHA mismatch: {digest}")
    return tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")


def member(archive, name):
    stream = archive.extractfile(name)
    if stream is None:
        raise RuntimeError("missing raw archive member " + name)
    return stream.read()


def checkpoint(archive, name):
    return json.loads(member(archive, name))


def events(archive, run):
    rows = []
    for line in member(archive, run + "/events.tsv").decode().splitlines():
        cells = line.split("\t")
        rows.append((int(cells[0]), cells[1], cells[2:-1]))
    return sorted(rows)


def healthy_receipts(archive):
    for run in ("healthy-a", "healthy-b"):
        receipt = checkpoint(archive, run + "/run.json")
        if receipt.get("exit_code") != 0 or \
                receipt.get("original_source_commit") != SOURCE_REVISION:
            raise RuntimeError(run + ": original JUnit/source receipt changed")


def selector(fields):
    return "@@".join(fields[:4])


def selected_guards(rows):
    leader = [f[0] for _, kind, f in rows if kind == "LEADER_BIND"]
    raw = {f[0] for _, kind, f in rows
           if kind == "SESSION_BIND" and len(f) >= 3 and f[2] == "movedSession"}
    if len(leader) != 1 or len(raw) != 1:
        raise RuntimeError("leader or raw moved-session identity is ambiguous")
    guards = [s for s, kind, f in rows if kind == "TARGET_GUARD" and len(f) >= 6
              and f[:5] == [CHECK, "peer:" + leader[0], "leader", leader[0],
                            "movedSession"]]
    if not guards:
        raise RuntimeError("selected owner/target guard absent")
    owners = {s: f for s, kind, f in rows if kind == "OWNER_BIND"}
    if any((s - 1 not in owners or owners[s - 1][:2] !=
            [leader[0], next(iter(raw))] or
            not owners[s - 1][2].startswith(("local:", "forwarder:")))
           for s in guards):
        raise RuntimeError("selected guard lacks same raw-session owner binding")
    return guards


def bound_io(rows, start, end, complete_only=False):
    chosen = set()
    for seq, kind, f in rows:
        if kind != "IO" or not start < seq < end or len(f) < 7 \
                or f[6] != "movedSession" or "session:movedSession" not in f[1]:
            continue
        if complete_only and not (
                f[0].startswith("org.apache.zookeeper.ClientCnxnSocketNIO#doIO:119:")
                or (f[0].startswith("org.apache.zookeeper.server.NIOServerCnxn#handleWrite:")
                    and f[0].endswith(":packetSent()V"))):
            continue
        chosen.add(selector(f))
    return chosen


def unbound_summary(rows):
    first_peer = min(s for s, kind, _ in rows if kind == "PEER_BIND")
    last_guard = selected_guards(rows)[-1]
    before = [f for s, kind, f in rows if kind == "UNBOUND_IO" and s < first_peer]
    between = [f for s, kind, f in rows
               if kind == "UNBOUND_IO" and first_peer < s < last_guard]
    return {
        "before_peer_bind": len(before),
        "before_peer_bind_file_io": sum("QuorumPeer#" in f[0] for f in before),
        "between_peer_bind_and_last_target": len(between),
        "between_unbound_reasons": dict(Counter(f[1] for f in between)),
        "between_file_io": sum("QuorumPeer#" in f[0] for f in between),
    }


def legacy_stage(label, complete_only=False):
    with open_archive(label) as archive:
        healthy_receipts(archive)
        cp = checkpoint(archive, "v2-campaign.json")
        seeds = [events(archive, name) for name in ("healthy-a", "healthy-b")]
        eligible = [bound_io(rows, 0, selected_guards(rows)[-1], complete_only)
                    for rows in seeds]
        stable = eligible[0] & eligible[1]
        root_plans = {r["plan"][0] for r in cp["results"] if len(r["plan"]) == 1}
        pending = [tuple(job["plan"]) for job in cp["pending"]]
        tested = [tuple(r["plan"]) for r in cp["results"]]
        tested_last = {plan[-1] for plan in tested}
        siblings = defaultdict(list)
        for row in cp["results"]:
            siblings[row.get("parent")].append(row)
        parents = sorted({job.get("parent") for job in cp["pending"]})
        same_parent_children = [row for parent in parents for row in siblings[parent]]
        if not stable <= root_plans or set(pending) & set(tested):
            raise RuntimeError(label + ": stable root selector missing or pending replay")
        if cp["status"] == "queue_exhausted" and pending:
            raise RuntimeError(label + ": purported exhausted queue has pending jobs")
        return {
            "status": cp["status"],
            "selected_attempts": len(tested),
            "effective": cp["effective_count"],
            "healthy_guard_counts": [len(selected_guards(rows)) for rows in seeds],
            "healthy_bound_pretarget_selectors": list(map(len, eligible)),
            "stable_bound_pretarget_selectors": len(stable),
            "stable_selectors_tested_as_single_fault": len(stable & root_plans),
            "pending_plans": len(pending),
            "pending_depths": dict(Counter(str(len(p)) for p in pending)),
            "pending_parent_count": len(parents),
            "pending_unique_last_selectors": len({p[-1] for p in pending}),
            "pending_last_selectors_not_previously_tested": len(
                {p[-1] for p in pending} - tested_last),
            "tested_children_of_pending_parents": len(same_parent_children),
            "effective_children_of_pending_parents": sum(
                bool(row["effective"]) for row in same_parent_children),
            "unbound_healthy": [unbound_summary(rows) for rows in seeds],
        }


def multiop_stage():
    with open_archive("multiop_pilot") as pilot, open_archive("multiop_campaign") as campaign:
        healthy_receipts(pilot)
        first = checkpoint(pilot, "pilot-checkpoint.json")
        later = checkpoint(campaign, "campaign/checkpoint.json")
        prefirst = checkpoint(campaign, "pre-first-checkpoint.json")
        seeds = [events(pilot, name) for name in ("healthy-a", "healthy-b")]
        guards = [selected_guards(rows) for rows in seeds]
        if any(len(g) != 2 for g in guards):
            raise RuntimeError("MultiOp healthy check count changed")
        inter = [bound_io(rows, g[0], g[1]) for rows, g in zip(seeds, guards)]
        before = [bound_io(rows, 0, g[0]) for rows, g in zip(seeds, guards)]
        inter_stable = inter[0] & inter[1]
        before_stable = before[0] & before[1]
        tried_one = {tuple(row["plan"]) for row in first["results"] + later["results"]
                     if len(row["plan"]) == 1}
        prefirst_queue = set(prefirst["queue"])
        if later["status"] != "queue_exhausted" or later["pending"] or later["inflight"]:
            raise RuntimeError("MultiOp interguard queue not terminal")
        if not inter_stable <= {plan[0] for plan in tried_one}:
            raise RuntimeError("untried stable MultiOp interguard selector")
        if before_stable != prefirst_queue or len(prefirst["results"]) != len(prefirst_queue):
            raise RuntimeError("MultiOp pre-first selectors not exhausted")
        return {
            "status": later["status"],
            "healthy_guard_counts": list(map(len, guards)),
            "healthy_bound_interguard_selectors": list(map(len, inter)),
            "stable_interguard_selectors": len(inter_stable),
            "stable_interguard_tested_as_single_fault": len(inter_stable),
            "stable_pre_first_selectors": len(before_stable),
            "stable_pre_first_tested": len(prefirst_queue),
            "pre_first_effective": sum(bool(r["effective"]) for r in prefirst["results"]),
            "pilot_selected": len(first["results"]),
            "formal_selected": len(later["results"]),
            "interguard_effective": later["effective_count"],
            "interguard_pending": len(later["pending"]),
            "unbound_healthy": [unbound_summary(rows) for rows in seeds],
        }


def main():
    out = {
        "case_id": "ZOOKEEPER-03",
        "target": CHECK,
        "source_revision": SOURCE_REVISION,
        "scope": "observed actor-bound IOException selectors in three original cluster-JUnit stages",
        "pre_io": legacy_stage("pre_io"),
        "post_response": legacy_stage("post_response", complete_only=True),
        "multiop": multiop_stage(),
        "new_stable_bound_selector_frontier": 0,
        "pre_io_remaining": "63 untried ordered plans at 32 previously tested exact last selectors",
        "verdict": "observed_identity_bound_selector_frontier_exhausted; effective_budget_unmet",
    }
    assert out["pre_io"]["pending_plans"] == 63
    assert out["pre_io"]["pending_last_selectors_not_previously_tested"] == 0
    assert out["post_response"]["pending_plans"] == 0
    assert out["multiop"]["interguard_pending"] == 0
    assert out["multiop"]["stable_pre_first_selectors"] == 4
    path = HERE / "evidence/frontier-audit.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"verdict": out["verdict"], "pre_pending": 63,
                      "post_pending": 0, "multiop_pending": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
