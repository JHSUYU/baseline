"""Convert GraphChecker/Soot JVM method signatures to agent site names."""

from __future__ import annotations

import re


METHOD = re.compile(r"^<([^:]+): ([^ ]+) ([^(]+)\(([^)]*)\)>$")
PRIMITIVES = {"void": "V", "boolean": "Z", "byte": "B", "char": "C",
              "short": "S", "int": "I", "long": "J", "float": "F",
              "double": "D"}


def descriptor_type(name: str) -> str:
    depth = 0
    while name.endswith("[]"):
        name = name[:-2]
        depth += 1
    if not name or "[" in name or "]" in name:
        raise ValueError("bad JVM type: " + name)
    return "[" * depth + PRIMITIVES.get(
        name, "L" + name.replace(".", "/") + ";")


def agent_method(signature: str) -> str:
    match = METHOD.fullmatch(signature)
    if match is None:
        raise ValueError("cannot parse Soot method: " + signature)
    owner, result, name, arguments = match.groups()
    params = [] if not arguments else arguments.split(",")
    return (owner.replace(".", "/") + "#" + name + "("
            + "".join(descriptor_type(part) for part in params) + ")"
            + descriptor_type(result))
