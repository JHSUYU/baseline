"""Pin Solr direct-JUnit case configs to a clean, isolated source lane.

This rewrites only the runtime source path.  It never edits adapter-owned
configs or reuses a result directory from another cohort.  Generated configs
are immutable after creation; changed adapter inputs require a new cohort.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    from .worker import atomic_json
except ImportError:
    from worker import atomic_json


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lane_config(config: dict, lane_root: Path) -> dict:
    if config.get("system", "").lower() != "solr":
        raise ValueError("lane config source is not Solr")
    old_root = config.get("source_equivalent_root")
    if not old_root or config.get("cwd") != old_root or config.get("source_overlay_receipt"):
        raise ValueError("Solr config does not declare a clean isolated source root")
    command = config.get("command", [])
    if not isinstance(command, list) or not any(
            Path(str(part)).name.startswith("run_pilot") and str(part).endswith(".py")
            for part in command):
        raise ValueError("Solr direct JUnit command is missing")
    command = list(command)
    if "--source" in command:
        index = command.index("--source")
        if index + 1 >= len(command) or command[index + 1] != old_root:
            raise ValueError("Solr command has an unexpected source root")
        command[index + 1] = str(lane_root)
    else:
        command.extend(["--source", str(lane_root)])
    result = dict(config)
    result["cwd"] = str(lane_root)
    result["source_equivalent_root"] = str(lane_root)
    result["command"] = command
    return result


def generate(input_root: Path, output_root: Path, lane_root: Path,
             case_ids: set[str] | None = None) -> dict:
    if not lane_root.is_absolute():
        raise ValueError("lane root must be absolute")
    sources = sorted(input_root.glob("SOLR-*/config.json"))
    if case_ids is not None:
        sources = [path for path in sources if path.parent.name in case_ids]
        missing = case_ids - {path.parent.name for path in sources}
        if missing:
            raise ValueError(f"missing Solr configs: {sorted(missing)}")
    if not sources:
        raise ValueError("no Solr configs found")
    rows = []
    for path in sources:
        config = json.loads(path.read_text(encoding="utf-8"))
        if config.get("case_id") != path.parent.name:
            raise ValueError(f"case ID differs from config path: {path}")
        transformed = lane_config(config, lane_root)
        encoded = json.dumps(transformed, sort_keys=True, indent=2) + "\n"
        destination = output_root / f"{config['case_id']}.json"
        if destination.exists():
            if destination.read_text(encoding="utf-8") != encoded:
                raise RuntimeError(f"existing lane config differs: {destination}")
        else:
            atomic_json(destination, transformed)
        rows.append({"case_id": config["case_id"], "input_path": str(path),
                     "input_sha256": digest(path), "output_path": str(destination),
                     "output_sha256": digest(destination)})
    manifest = {"schema_version": 1, "lane_id": "solr-lane2",
                "source_root": str(lane_root), "configs": rows}
    manifest_path = output_root / "manifest.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
        raise RuntimeError(f"existing lane manifest differs: {manifest_path}")
    if not manifest_path.exists():
        atomic_json(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path,
                        default=Path("Mallory/adapters/solr/cases"))
    parser.add_argument("--output-root", type=Path,
                        default=Path("Mallory/dispatch/lane_configs/solr-v2-lane2"))
    parser.add_argument("--lane-root", type=Path,
                        default=Path.home() / ".mallory-worktrees/solr-lane2")
    parser.add_argument("--only", nargs="*", help="specific Solr case IDs")
    args = parser.parse_args()
    manifest = generate(args.input_root, args.output_root, args.lane_root,
                        set(args.only) if args.only else None)
    print(json.dumps({"lane_id": manifest["lane_id"],
                      "configs": len(manifest["configs"]),
                      "manifest": str(args.output_root / "manifest.json")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
