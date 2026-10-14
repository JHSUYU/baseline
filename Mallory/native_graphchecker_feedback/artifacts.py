"""Locate a Recorder region plan without changing its legacy identity."""

from pathlib import Path


def region_plan_path(recorded_dir: Path) -> Path:
    """Prefer the lossless compressed plan; accept older plaintext recordings."""
    compressed = recorded_dir / "concolic_region_plan.jsonl.gz"
    if compressed.is_file():
        return compressed
    return recorded_dir / "concolic_region_plan.jsonl"
