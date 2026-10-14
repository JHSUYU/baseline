"""Optional writable build cache for original GraphChecker feedback helpers.

The default remains the established in-tree ``target`` directory. A runner
with read-only source inputs can set ``MALLORY_FEEDBACK_BUILD_CACHE_ROOT`` to
an absolute, task-local writable directory.
"""

from __future__ import annotations

import os
from pathlib import Path


ENV = "MALLORY_FEEDBACK_BUILD_CACHE_ROOT"
_COMPONENTS = frozenset(("region-plan-ids", "native-feedback"))


def component_root(component: str, default: Path) -> Path:
    if component not in _COMPONENTS:
        raise ValueError("unknown feedback cache component")
    raw = os.environ.get(ENV)
    if not raw:
        return default
    root = Path(raw)
    if not root.is_absolute():
        raise ValueError(f"{ENV} must be an absolute path")
    output = root / component
    output.mkdir(parents=True, exist_ok=True)
    return output
