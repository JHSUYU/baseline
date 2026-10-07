#!/usr/bin/env python3
"""Find one internally consistent ASM installation for JaCoCo analysis."""

from pathlib import Path


def asm_jars() -> list[Path]:
    root = Path.home() / ".m2/repository/org/ow2/asm"
    modules = ("asm", "asm-tree", "asm-commons")
    versions = [set((root / module).iterdir()) if (root / module).exists() else set()
                for module in modules]
    common = set.intersection(*({path.name for path in group} for group in versions))
    common = {version for version in common if all(part.isdigit() for part in version.split("."))}
    for version in sorted(common, key=lambda text: tuple(int(part) for part in text.split(".")),
                          reverse=True):
        jars = [root / module / version / f"{module}-{version}.jar" for module in modules]
        if all(path.is_file() for path in jars):
            return jars
    raise RuntimeError("JaCoCo method/branch feedback needs matching ASM core/tree/commons jars")
