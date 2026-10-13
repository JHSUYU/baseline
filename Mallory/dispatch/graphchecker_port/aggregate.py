"""Build the 102-check table from durable native GraphChecker receipts.

Reads each case on its owner host. It never changes a trial or checkpoint.
Without --out, the TSV is printed to stdout.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from Mallory.dispatch.graphchecker_port.plan import CASE_ID, SYSTEM_WAVES, sha256

FIELDS = (
    "case_id", "system", "system_version", "eligibility_state",
    "target_source_path", "target_class", "target_method", "target_line",
    "target_exception", "junit_workload", "junit_class", "junit_method",
    "config_sha256", "receipt_host", "receipt_status", "terminal",
    "completed_fault_trials", "strict_trials", "post_fault_target_trials",
    "strict_post_fault_target_trials", "target_exception_triggered_trials",
    "target_exception_candidate_count", "elapsed_seconds", "elapsed_basis",
    "quality_state", "quality_reason", "bug_review_mark", "review_evidence",
    "checkpoint_path", "summary_path",
    "receipt_error",
)

DEFAULT_QUALITY_FILE = Path(__file__).with_name("quality_reviews.json")
QUALITY_STATES = {"budget_finished_preliminary", "high_quality_complete", "needs_rerun"}


def _owner(system: str) -> str:
    for wave in SYSTEM_WAVES:
        for host, assigned in wave.items():
            if assigned == system:
                return host
    raise ValueError(f"unknown system: {system}")


def _load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError(f"JSON object required: {path}")
    return result


class ReceiptReader:
    def __init__(self, state_root: Path, *, remote: bool,
                 ssh_key: Path | None = None,
                 imports: dict[str, Path] | None = None):
        self.state_root = state_root.resolve()
        self.remote = remote
        self.ssh_key = ssh_key or (Path.home() / ".ssh/id_ed25519_nodes")
        self.imports = imports or {}

    def read(self, case_id: str, host: str) -> tuple[dict | None, dict | None]:
        if case_id in self.imports:
            root = self.imports[case_id]
            return _load_json(root / "checkpoint.json"), _load_json(root / "summary.json")
        if not self.remote or host == "node0":
            root = self.state_root / case_id
            return _load_json(root / "checkpoint.json"), _load_json(root / "summary.json")
        if not CASE_ID.fullmatch(case_id) or host not in ("node1", "node2"):
            raise ValueError("unsafe remote receipt request")
        script = ("import json,sys; from pathlib import Path; "
                  "r=Path(sys.argv[1])/sys.argv[2]; "
                  "print(json.dumps([(r/n).read_text() if (r/n).is_file() else None "
                  "for n in ('checkpoint.json','summary.json')]))")
        remote_argv = ["python3", "-c", script, str(self.state_root), case_id]
        result = subprocess.run([
            "ssh", "-i", str(self.ssh_key), "-o", "IdentitiesOnly=yes",
            "-o", "BatchMode=yes", f"ZhenyuLi@{host}", shlex.join(remote_argv)],
            capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise OSError(f"remote receipt read failed on {host}: {result.stderr[:200]}")
        texts = json.loads(result.stdout)
        if not isinstance(texts, list) or len(texts) != 2:
            raise ValueError(f"invalid remote receipt envelope from {host}")
        values = [json.loads(value) if value is not None else None for value in texts]
        if any(value is not None and not isinstance(value, dict) for value in values):
            raise ValueError(f"invalid remote receipt object from {host}")
        return values[0], values[1]


def load_import_index(path: Path) -> dict[str, Path]:
    """Resolve only complete, hash-verified local receipt snapshots."""
    index = _load_json(path)
    if index is None or index.get("schema_version") != 1 or not isinstance(
            index.get("cases"), dict):
        raise ValueError("invalid import index")
    root = path.resolve().parent
    result = {}
    for case_id, relative in index["cases"].items():
        if (not isinstance(case_id, str) or not CASE_ID.fullmatch(case_id)
                or not isinstance(relative, str)
                or not re.fullmatch(r"imports/" + re.escape(case_id) +
                                    r"/[0-9a-f]{16}-[0-9a-f]{12}", relative)):
            raise ValueError("invalid imported case path")
        directory = root / relative
        receipt = _load_json(directory / "import-receipt.json")
        if receipt is None or receipt.get("schema_version") != 1 or (
                receipt.get("case_id") != case_id):
            raise ValueError(f"invalid import receipt: {case_id}")
        hashes = receipt.get("source_sha256")
        if not isinstance(hashes, dict) or any(
                not isinstance(hashes.get(name), str) or
                sha256(directory / ("config.json" if name == "config" else name + ".json"))
                != hashes[name]
                for name in ("config", "checkpoint", "summary")):
            raise ValueError(f"imported receipt bytes changed: {case_id}")
        result[case_id] = directory
    return result


def _review_rows(path: Path | None) -> dict[str, dict]:
    if path is None:
        return {}
    document = _load_json(path)
    if document is None or document.get("schema_version") != 1:
        raise ValueError("review file needs schema_version 1")
    items = document.get("reviews")
    if not isinstance(items, list):
        raise ValueError("review file needs reviews list")
    result = {}
    for item in items:
        if (not isinstance(item, dict) or not isinstance(item.get("case_id"), str)
                or not CASE_ID.fullmatch(item["case_id"])
                or item.get("mark") not in ("confirmed", "rejected")
                or not isinstance(item.get("reviewer"), str) or not item["reviewer"]
                or not isinstance(item.get("evidence_paths"), list)
                or not item["evidence_paths"]
                or any(not isinstance(path, str) or not path
                       for path in item["evidence_paths"])
                or item["case_id"] in result):
            raise ValueError("invalid or duplicate manual review")
        result[item["case_id"]] = item
    return result


def _quality_rows(path: Path | None) -> dict[str, dict]:
    if path is None:
        return {}
    document = _load_json(path)
    if document is None or document.get("schema_version") != 1:
        raise ValueError("quality file needs schema_version 1")
    items = document.get("quality_reviews")
    if not isinstance(items, list):
        raise ValueError("quality file needs quality_reviews list")
    result = {}
    for item in items:
        if (not isinstance(item, dict)
                or not isinstance(item.get("case_id"), str)
                or not CASE_ID.fullmatch(item["case_id"])
                or item["case_id"] in result
                or item.get("state") not in QUALITY_STATES
                or not isinstance(item.get("reason"), str) or not item["reason"].strip()
                or not isinstance(item.get("config_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", item["config_sha256"]) is None
                or not isinstance(item.get("receipt_status"), str)
                or not item["receipt_status"]
                or type(item.get("completed_fault_trials")) is not int
                or item["completed_fault_trials"] < 0
                or not isinstance(item.get("evidence_paths"), list)
                or not item["evidence_paths"]
                or any(not isinstance(p, str) or not p for p in item["evidence_paths"])):
            raise ValueError("invalid or duplicate quality review")
        result[item["case_id"]] = item
    return result


def _trial_metrics(checkpoint: dict, summary: dict | None) -> dict:
    trials = checkpoint.get("trials")
    if not isinstance(trials, list):
        raise ValueError("checkpoint lacks trials list")
    if any(not isinstance(trial, dict) for trial in trials):
        raise ValueError("checkpoint trial is not an object")
    count = checkpoint.get("completed_fault_trials")
    if not isinstance(count, int) or count != len(trials):
        raise ValueError("completed trial count disagrees with checkpoint records")
    metrics = {
        "completed_fault_trials": count,
        "strict_trials": sum(trial.get("strict_injection") is True for trial in trials),
        "post_fault_target_trials": sum(trial.get("post_fault_target_reached") is True
                                        for trial in trials),
        "strict_post_fault_target_trials": sum(
            trial.get("strict_injection") is True and
            trial.get("post_fault_target_reached") is True for trial in trials),
        "target_exception_triggered_trials": sum(
            trial.get("target_exception_triggered") is True for trial in trials),
        "target_exception_candidate_count": sum(
            trial.get("target_exception_candidate") is True for trial in trials),
        "elapsed_seconds": checkpoint.get("trial_elapsed_seconds"),
        "elapsed_basis": "sum_trial_elapsed",
    }
    if not isinstance(metrics["elapsed_seconds"], (int, float)) or metrics["elapsed_seconds"] < 0:
        raise ValueError("invalid trial elapsed seconds")
    if summary is not None:
        pairs = (("completed_fault_trials", "completed_fault_trials"),
                 ("strict_trials", "strict_trials"),
                 ("post_fault_target_trials", "post_fault_target_trials"),
                 ("target_exception_triggered_trials", "target_exception_triggered_trials"),
                 ("differential_candidates", "target_exception_candidate_count"))
        for summary_key, metric_key in pairs:
            if summary.get(summary_key) != metrics[metric_key]:
                raise ValueError(f"summary disagrees with checkpoint: {summary_key}")
        if abs(float(summary.get("trial_elapsed_seconds", -1)) -
               float(metrics["elapsed_seconds"])) > 0.01:
            raise ValueError("summary trial elapsed differs from checkpoint")
    return metrics


def _native_status(case_id: str, checkpoint: dict | None,
                   summary: dict | None, config_digest: str | None) -> tuple[str, bool, dict]:
    if checkpoint is None:
        if summary is not None:
            raise ValueError("summary exists without checkpoint")
        return "unrun", False, {}
    if (checkpoint.get("schema_version") != 1 or checkpoint.get("case_id") != case_id
            or not isinstance(checkpoint.get("config_sha256"), str)):
        raise ValueError("invalid checkpoint identity")
    if config_digest is not None and checkpoint["config_sha256"] != config_digest:
        raise ValueError("checkpoint config fingerprint differs from local config")
    terminal = checkpoint.get("terminal")
    status = checkpoint.get("status")
    if terminal is True:
        if (not isinstance(summary, dict) or summary.get("schema_version") != 1
                or summary.get("terminal") is not True
                or summary.get("case_id") != case_id
                or summary.get("status") != status
                or summary.get("config_sha256") != checkpoint["config_sha256"]):
            raise ValueError("terminal checkpoint lacks matching summary")
    elif terminal is False and status == "running":
        if summary is not None:
            raise ValueError("running checkpoint has terminal summary")
    else:
        raise ValueError("unknown checkpoint terminal/status combination")
    if not isinstance(status, str):
        raise ValueError("checkpoint status must be a string")
    return status, terminal, _trial_metrics(checkpoint, summary)


def _workload(item: dict, config: dict | None) -> tuple[str, str, str]:
    if config is not None:
        junit = config.get("junit")
        if isinstance(junit, dict):
            clazz, method = junit.get("class"), junit.get("method")
            if isinstance(clazz, str) and isinstance(method, str):
                return f"{clazz}#{method}", clazz, method
    workload = item.get("workload", {})
    selector = workload.get("selected_selector") or ""
    clazz = workload.get("test_class") or ""
    method = workload.get("test_method") or ""
    return selector, clazz, method


def aggregate(inventory_path: Path, config_root: Path, state_root: Path,
              reader: ReceiptReader, review_path: Path | None = None,
              quality_path: Path | None = DEFAULT_QUALITY_FILE,
              imports: dict[str, Path] | None = None) -> list[dict]:
    inventory = _load_json(inventory_path)
    if inventory is None or inventory.get("schema_version") != 1:
        raise ValueError("invalid inventory")
    cases = inventory.get("cases")
    if not isinstance(cases, list) or len(cases) != 102:
        raise ValueError("expected exactly 102 inventory cases")
    reviews = _review_rows(review_path)
    quality_reviews = _quality_rows(quality_path)
    seen = set()
    rows = []
    for item in cases:
        case_id, system = item.get("case_id"), item.get("system")
        if (not isinstance(case_id, str) or not CASE_ID.fullmatch(case_id)
                or case_id in seen or case_id.split("-", 1)[0].lower() != system):
            raise ValueError(f"invalid inventory case: {case_id}")
        seen.add(case_id)
        target = item["target"]
        function = target["function"]
        head = function.split("(", 1)[0]
        clazz, method = head.rsplit(".", 1)
        imported = (imports or {}).get(case_id)
        config_path = (imported / "config.json" if imported is not None else
                       config_root / (case_id + ".json"))
        config = _load_json(config_path)
        if config is not None and config.get("case_id") != case_id:
            raise ValueError(f"config case identity mismatch: {case_id}")
        config_digest = sha256(config_path) if config is not None else None
        selector, junit_class, junit_method = _workload(item, config)
        host = _owner(system)
        row = {key: "" for key in FIELDS}
        row.update({"case_id": case_id, "system": system,
                    "system_version": item.get("system_version", ""),
                    "eligibility_state": item.get("eligibility", {}).get("state", ""),
                    "target_source_path": target["source_path"],
                    "target_class": clazz, "target_method": method +
                    "(" + function.split("(", 1)[1],
                    "target_line": target["source_line"],
                    "target_exception": target.get("runtime_mapping", {}).get(
                        "exception_class", target.get("target_exception", "")),
                    "junit_workload": selector, "junit_class": junit_class,
                    "junit_method": junit_method,
                    "config_sha256": config_digest or "",
                    "receipt_host": host,
                    "checkpoint_path": str((imported if imported is not None else
                                            state_root / case_id) / "checkpoint.json"),
                    "summary_path": str((imported if imported is not None else
                                         state_root / case_id) / "summary.json")})
        row["quality_state"] = "unassessed"
        try:
            checkpoint, summary = reader.read(case_id, host)
            status, terminal, metrics = _native_status(
                case_id, checkpoint, summary, config_digest)
            row.update(metrics)
            row["receipt_status"] = status
            row["terminal"] = str(terminal).lower()
            if checkpoint is not None and not row["config_sha256"]:
                row["config_sha256"] = checkpoint["config_sha256"]
        except (OSError, ValueError, TypeError, KeyError) as error:
            row["receipt_status"] = "receipt_error"
            row["terminal"] = ""
            row["bug_review_mark"] = "needs_review"
            row["receipt_error"] = str(error)
        else:
            candidates = int(row.get("target_exception_candidate_count") or 0)
            review = reviews.get(case_id)
            if review is not None:
                if review["mark"] == "confirmed" and candidates == 0:
                    raise ValueError(f"cannot confirm {case_id} without a native candidate")
                row["bug_review_mark"] = review["mark"]
                row["review_evidence"] = ";".join(review["evidence_paths"])
            else:
                row["bug_review_mark"] = "candidate" if candidates else "none"
        quality = quality_reviews.get(case_id)
        if quality is not None:
            pinned = (row["receipt_status"] == quality["receipt_status"]
                      and row["config_sha256"] == quality["config_sha256"]
                      and row["completed_fault_trials"] == quality["completed_fault_trials"]
                      and row["terminal"] == "true")
            if pinned:
                row["quality_state"] = quality["state"]
                row["quality_reason"] = quality["reason"]
            else:
                row["quality_reason"] = (
                    "Quality review is stale for the current config or receipt; reassess this run.")
        rows.append(row)
    if set(reviews) - seen:
        raise ValueError("review file names a case outside inventory")
    if set(quality_reviews) - seen:
        raise ValueError("quality file names a case outside inventory")
    return rows


def render_tsv(rows: list[dict]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=FIELDS, delimiter="\t",
                            lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path,
                        default=Path("Mallory/cases/inventory.json"))
    parser.add_argument("--config-root", type=Path,
                        default=Path("data/mallory/graphchecker_port/configs"))
    parser.add_argument("--state-root", type=Path,
                        default=Path("data/mallory/graphchecker_port/cases"))
    parser.add_argument("--review-file", type=Path)
    parser.add_argument("--quality-file", type=Path, default=DEFAULT_QUALITY_FILE)
    parser.add_argument("--import-index", type=Path,
                        help="Atomically selected, locally verified campaign snapshots")
    parser.add_argument("--local-only", action="store_true",
                        help="Read all case receipts locally; intended for mirrored fixtures")
    parser.add_argument("--ssh-key", type=Path,
                        default=Path.home() / ".ssh/id_ed25519_nodes")
    parser.add_argument("--out", type=Path,
                        help="Atomically replace a derived TSV; trial data stays read-only")
    args = parser.parse_args()
    state_root = args.state_root.resolve()
    imports = load_import_index(args.import_index) if args.import_index else {}
    reader = ReceiptReader(state_root, remote=not args.local_only,
                           ssh_key=args.ssh_key, imports=imports)
    rows = aggregate(args.inventory.resolve(), args.config_root.resolve(), state_root,
                     reader, args.review_file, args.quality_file, imports)
    output = render_tsv(rows)
    if args.out is None:
        print(output, end="")
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.out.with_name("." + args.out.name + f".tmp.{os.getpid()}")
        temporary.write_text(output, encoding="utf-8")
        temporary.replace(args.out)
        print(json.dumps({"rows": len(rows), "output": str(args.out),
                          "inventory_sha256": sha256(args.inventory),
                          "generated_at": datetime.now(timezone.utc).isoformat()},
                         sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
