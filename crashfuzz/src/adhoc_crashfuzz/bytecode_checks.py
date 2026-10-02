"""Map a source throw to one direct guarding JVM conditional branch."""

from __future__ import annotations

import re
import subprocess
from typing import Optional


SECTION = re.compile(r"(?=^  [^\n]+;\n    descriptor: )", re.MULTILINE)
HEADER = re.compile(r"(?m)^  ([^\n]+);\n    descriptor: ([^\n]+)")
INSTRUCTION = re.compile(
    r"(?m)^[ \t]+(\d+): ([a-z][a-z0-9_]*)\b(?:[ \t]+(\d+))?")
LINE = re.compile(r"(?m)^\s+line (\d+): (\d+)")


def map_direct_throw(agent_method: str, source_line: int,
                     javap_text: str) -> Optional[dict]:
    """Return bytecode sites only for an unambiguous direct guard/throw."""
    owner, rest = agent_method.split("#", 1)
    method = rest.split("(", 1)[0]
    descriptor = rest[len(method):]
    matching = []
    for section in SECTION.split(javap_text):
        header = HEADER.search(section)
        if header is None or header.group(2) != descriptor:
            continue
        declaration = header.group(1)
        if method == "<init>":
            if owner.rsplit("/", 1)[-1].split("$")[-1] not in declaration:
                continue
        elif re.search(r"\b" + re.escape(method) + r"\(", declaration) is None:
            continue
        matching.append(section)
    if len(matching) != 1:
        return None
    section = matching[0]
    instructions = [(int(pc), opcode, None if not argument
                     else int(argument))
                    for pc, opcode, argument in INSTRUCTION.findall(section)]
    lines = sorted((int(pc), int(line)) for line, pc in LINE.findall(section))
    throw_pcs = []
    for pc, opcode, _ in instructions:
        if opcode != "athrow":
            continue
        before = [line for start, line in lines if start <= pc]
        if before and before[-1] == source_line:
            throw_pcs.append(pc)
    if len(throw_pcs) != 1:
        return None
    throw_pc = throw_pcs[0]
    following = [pc for pc, _, _ in instructions if pc > throw_pc]
    if not following:
        return None
    after_throw = min(following)
    branches = [(pc, index)
                for index, (pc, opcode, target) in enumerate(
                    (item for item in instructions if item[1].startswith("if")), 1)
                if pc < throw_pc and target == after_throw]
    if not branches:
        return None
    guard_pc, guard_index = max(branches)
    # Another throw or unconditional jump between the guard and this throw
    # makes its direct control relation ambiguous.
    if any(guard_pc < pc < throw_pc and
           (opcode == "athrow" or opcode.startswith("goto"))
           for pc, opcode, _ in instructions):
        return None
    return {"guard": agent_method + "#B" + str(guard_index),
            "throw": agent_method + "#L" + str(source_line),
            "guard_offset": guard_pc, "throw_offset": throw_pc}


def javap_class(classpath: str, classname: str) -> str:
    result = subprocess.run(["javap", "-classpath", classpath,
                             "-c", "-l", "-s", "-p", classname],
                            capture_output=True, text=True, timeout=60,
                            check=True)
    return result.stdout
