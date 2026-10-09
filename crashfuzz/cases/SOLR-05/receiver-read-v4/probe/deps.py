#!/usr/bin/env python3
"""Find one internally consistent ASM installation for JaCoCo analysis."""

import fcntl
from pathlib import Path
import shutil
import subprocess
import time


def guarded_check_output(command: list[str], workdir: Path) -> str:
    """Start a coverage helper JVM under the same node resource gate as JUnit."""
    gate_path = Path("/users/ZhenyuLi/baseline/crashfuzz/jvm-start.lock")
    with gate_path.open("a+") as gate:
        while True:
            fcntl.flock(gate, fcntl.LOCK_EX)
            running = subprocess.run(["pgrep", "-c", "java"],
                                     capture_output=True, text=True, check=False)
            count = int(running.stdout.strip() or 0)
            if count < 5 and shutil.disk_usage(workdir).free >= 3 * 1024**3:
                proc = subprocess.Popen(command, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True)
                fcntl.flock(gate, fcntl.LOCK_UN)
                output, errors = proc.communicate()
                if proc.returncode:
                    raise subprocess.CalledProcessError(proc.returncode, command,
                                                        output, errors)
                return output
            fcntl.flock(gate, fcntl.LOCK_UN)
            time.sleep(10)


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
