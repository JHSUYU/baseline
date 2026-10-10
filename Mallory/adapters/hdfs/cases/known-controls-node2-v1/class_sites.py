#!/usr/bin/env python3
"""Read class-file line/branch/throw positions without launching a JVM."""

from __future__ import annotations

import struct
from pathlib import Path


class Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def u1(self):
        value = self.data[self.pos]
        self.pos += 1
        return value

    def u2(self):
        value = struct.unpack_from(">H", self.data, self.pos)[0]
        self.pos += 2
        return value

    def u4(self):
        value = struct.unpack_from(">I", self.data, self.pos)[0]
        self.pos += 4
        return value

    def take(self, size):
        value = self.data[self.pos:self.pos + size]
        self.pos += size
        return value


def class_methods(path: Path):
    reader = Reader(path.read_bytes())
    assert reader.u4() == 0xCAFEBABE
    reader.take(4)
    pool = [None]
    count = reader.u2()
    while len(pool) < count:
        tag = reader.u1()
        if tag == 1:
            pool.append(reader.take(reader.u2()).decode("utf-8", "replace"))
        elif tag in (3, 4, 9, 10, 11, 12, 17, 18):
            reader.take(4)
            pool.append(None)
        elif tag in (5, 6):
            reader.take(8)
            pool.extend((None, None))
        elif tag in (7, 8, 16, 19, 20):
            reader.take(2)
            pool.append(None)
        elif tag == 15:
            reader.take(3)
            pool.append(None)
        else:
            raise ValueError(f"unknown class-file constant tag {tag}")
    reader.take(6)
    reader.take(reader.u2() * 2)

    def attributes(target=None):
        result = {}
        for _ in range(reader.u2()):
            name = pool[reader.u2()]
            data = reader.take(reader.u4())
            if target is None or name in target:
                result[name] = data
        return result

    for _ in range(reader.u2()):
        reader.take(6)
        attributes(set())
    result = {}
    for _ in range(reader.u2()):
        reader.take(2)
        name, descriptor = pool[reader.u2()], pool[reader.u2()]
        payload = attributes({"Code"}).get("Code")
        if not payload:
            continue
        code_reader = Reader(payload)
        code_reader.take(4)
        code = code_reader.take(code_reader.u4())
        code_reader.take(code_reader.u2() * 8)
        lines = {}
        for _ in range(code_reader.u2()):
            attribute_name = pool[code_reader.u2()]
            data = Reader(code_reader.take(code_reader.u4()))
            if attribute_name == "LineNumberTable":
                for _ in range(data.u2()):
                    start_pc, source_line = data.u2(), data.u2()
                    lines[start_pc] = source_line
        result[(name, descriptor)] = (code, lines)
    return result


def instruction_sites(path: Path, name: str):
    methods = class_methods(path)
    chosen = [(descriptor, code, lines) for (method, descriptor), (code, lines)
              in methods.items() if method == name]
    if len(chosen) != 1:
        raise ValueError(f"expected exactly one method {name} in {path}")
    descriptor, code, lines = chosen[0]
    fixed_two = {16, 18, 21, 22, 23, 24, 25, 54, 55, 56, 57, 58, 169, 188}
    fixed_three = {17, 19, 20, 132, 178, 179, 180, 181, 182, 183, 184, 187, 189,
                   192, 193, 198, 199} | set(range(153, 169))
    fixed_four = {197}
    fixed_five = {185, 186, 200, 201}
    offset = branch_index = throw_index = door_index = 0
    line = -1
    sites = []
    while offset < len(code):
        line = lines.get(offset, line)
        opcode = code[offset]
        if opcode in set(range(153, 167)) | {170, 171, 198, 199}:
            branch_index += 1
            sites.append(("branch", line, branch_index, offset))
        elif opcode == 191:
            throw_index += 1
            sites.append(("throw", line, throw_index, offset))
        elif opcode in (182, 183, 184, 185):
            door_index += 1
            sites.append(("call", line, door_index, offset))
        if opcode in fixed_two:
            width = 2
        elif opcode in fixed_three:
            width = 3
        elif opcode in fixed_four:
            width = 4
        elif opcode in fixed_five:
            width = 5
        elif opcode == 196:
            width = 6 if code[offset + 1] == 132 else 4
        elif opcode == 170:
            start = (offset + 4) & ~3
            low, high = struct.unpack_from(">ii", code, start + 4)
            width = start + 12 + 4 * (high - low + 1) - offset
        elif opcode == 171:
            start = (offset + 4) & ~3
            pairs = struct.unpack_from(">i", code, start + 4)[0]
            width = start + 8 + 8 * pairs - offset
        else:
            width = 1
        offset += width
    if offset != len(code):
        raise ValueError(f"instruction scan ended at {offset} of {len(code)}")
    return descriptor, sites
