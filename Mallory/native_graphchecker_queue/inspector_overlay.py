"""Verify a reviewed, inspector-only patch over executed campaign Python.

The executed source tree remains immutable.  An overlay may replace only the
native checklist module during a read-only audit; every other import still
comes from the campaign's pinned Python tree.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
from pathlib import Path
from typing import Any


MODULE = "Mallory/native_graphchecker_dispatch/checklist.py"
METHOD = "pinned_archived_python_reviewed_inspector_overlay_full_native_inspect_case"
_KEYS = {"schema_version", "module", "base_sha256", "patched_path",
         "patched_sha256", "diff_path", "diff_sha256", "changed_symbols"}


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _regular_pinned(path_value: Any, digest: Any, label: str) -> tuple[Path, bytes]:
    if (not isinstance(path_value, str) or not isinstance(digest, str) or
            len(digest) != 64):
        raise ValueError(f"invalid inspector overlay {label} pin")
    path = Path(path_value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError(f"inspector overlay {label} is not a regular absolute file")
    data = path.read_bytes()
    if _sha_bytes(data) != digest:
        raise ValueError(f"inspector overlay {label} bytes changed")
    return path, data


def _changed_symbols(original: str, patched: str) -> list[str]:
    try:
        before = ast.parse(original, filename=MODULE)
        after = ast.parse(patched, filename=MODULE)
    except SyntaxError as error:
        raise ValueError("inspector overlay contains invalid Python") from error

    def parts(tree: ast.AST) -> tuple[list[tuple[str, str]], dict[str, str]]:
        order = []
        symbols: dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                if node.name in symbols:
                    raise ValueError("duplicate inspector overlay top-level symbol")
                symbols[node.name] = ast.dump(node, include_attributes=False)
                order.append(("symbol", node.name))
            else:
                order.append(("statement", ast.dump(node,
                                                    include_attributes=False)))
        return order, symbols

    before_order, before_symbols = parts(before)
    after_order, after_symbols = parts(after)
    if (set(before_symbols) - set(after_symbols) or
            before_order != [entry for entry in after_order
                             if entry[0] != "symbol" or
                             entry[1] in before_symbols]):
        raise ValueError("inspector overlay changed top-level statement order")
    changed = sorted(name for name in before_symbols.keys() | after_symbols.keys()
                     if before_symbols.get(name) != after_symbols.get(name))
    if not changed:
        raise ValueError("inspector overlay does not change a named symbol")
    return changed


def verify_inspector_overlay(source: dict, source_root: Path, pin: dict
                             ) -> dict[str, Any]:
    """Return exact patch metadata; reject unrelated module or pin changes."""
    if (not isinstance(pin, dict) or set(pin) != _KEYS or
            pin.get("schema_version") != 1 or pin.get("module") != MODULE or
            not isinstance(pin.get("changed_symbols"), list) or
            not pin["changed_symbols"] or
            pin["changed_symbols"] != sorted(set(pin["changed_symbols"])) or
            not all(isinstance(name, str) and name.isidentifier()
                    for name in pin["changed_symbols"])):
        raise ValueError("invalid versioned inspector overlay schema")
    expected_base = source.get("python_sha256", {}).get(MODULE)
    if pin["base_sha256"] != expected_base:
        raise ValueError("inspector overlay base differs from executed source")
    base_path = source_root / MODULE
    if base_path.is_symlink() or not base_path.is_file():
        raise ValueError("executed inspector source is missing")
    base_bytes = base_path.read_bytes()
    if _sha_bytes(base_bytes) != expected_base:
        raise ValueError("executed inspector source changed")
    patched_path, patched_bytes = _regular_pinned(
        pin["patched_path"], pin["patched_sha256"], "patched output")
    diff_path, diff_bytes = _regular_pinned(
        pin["diff_path"], pin["diff_sha256"], "unified diff")
    try:
        before = base_bytes.decode("utf-8")
        after = patched_bytes.decode("utf-8")
        expected_diff = "".join(difflib.unified_diff(
            before.splitlines(keepends=True), after.splitlines(keepends=True),
            fromfile=f"a/{MODULE}", tofile=f"b/{MODULE}"))
    except UnicodeDecodeError as error:
        raise ValueError("inspector overlay source is not UTF-8") from error
    if diff_bytes != expected_diff.encode("utf-8"):
        raise ValueError("inspector overlay diff does not produce pinned output")
    if _changed_symbols(before, after) != pin["changed_symbols"]:
        raise ValueError("inspector overlay changed undeclared symbols")
    return {"schema_version": 1, "module": MODULE,
            "base_sha256": expected_base,
            "patched_path": str(patched_path),
            "patched_sha256": pin["patched_sha256"],
            "diff_path": str(diff_path), "diff_sha256": pin["diff_sha256"],
            "changed_symbols": pin["changed_symbols"]}
