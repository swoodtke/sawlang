#!/usr/bin/env python3
"""Read-only SL-350 LLVM-IR census, comparison, and structural proof utility."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path


DEFINE_RE = re.compile(r'^define\b.*@(?:"([^"]+)"|([^\s(]+))\(')
LABEL_RE = re.compile(
    r'^((?:[A-Za-z$._][-A-Za-z0-9$._]*|[0-9]+|"[^"]+")):(?:\s*;.*)?$')
OPCODES = frozenset("""
    add addrspacecast alloca and ashr atomicrmw bitcast br call callbr
    catchpad catchret catchswitch cleanupret cleanuppad cmpxchg extractelement
    extractvalue fadd fcmp fdiv fence fmul fneg fpext fptosi fptoui fptrunc
    frem fsub freeze getelementptr icmp indirectbr insertelement insertvalue
    inttoptr invoke landingpad load lshr mul or phi ptrtoint resume ret sdiv
    select sext shl shufflevector sitofp srem store sub switch trunc udiv
    uitofp unreachable urem va_arg xor zext
""".split())
OPCODE_RE = re.compile(
    r'^\s+(?:(?:%(?:"[^"]+"|[-A-Za-z0-9$._]+))\s*=\s*)?'
    r'(?:(?:tail|musttail|notail)\s+)?([a-z][a-z0-9.]*)\b')


def instruction_opcode(line: str) -> str | None:
    match = OPCODE_RE.match(line)
    if match is None or match.group(1) not in OPCODES:
        return None
    return match.group(1)


@dataclass(frozen=True)
class Block:
    name: str
    lines: tuple[str, ...]

    @property
    def instructions(self) -> int:
        return sum(instruction_opcode(line) is not None for line in self.lines)

    @property
    def insertvalue(self) -> int:
        return sum(instruction_opcode(line) == 'insertvalue'
                   for line in self.lines)

    @property
    def slot_empty(self) -> int:
        return sum(instruction_opcode(line) in ('call', 'invoke')
                   and 'Slot' in line and 'empty' in line
                   for line in self.lines)

    @property
    def memset(self) -> int:
        return sum(instruction_opcode(line) in ('call', 'invoke')
                   and 'llvm.memset' in line for line in self.lines)

    @property
    def memcpy(self) -> int:
        return sum(instruction_opcode(line) in ('call', 'invoke')
                   and 'llvm.memcpy' in line for line in self.lines)

    @property
    def stores(self) -> int:
        return sum(instruction_opcode(line) == 'store' for line in self.lines)


@dataclass(frozen=True)
class Function:
    name: str
    text: str
    blocks: tuple[Block, ...]

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()

    @property
    def largest(self) -> Block:
        """Return the block with the greatest exact instruction count."""
        return max(self.blocks, key=lambda block: (
            block.instructions,
            block.name,
        ))

    @property
    def init_candidate(self) -> Block:
        """Return the block most likely to contain aggregate initialization."""
        return max(self.blocks, key=lambda block: (
            bool(block.slot_empty or block.memset),
            block.slot_empty + block.memset,
            block.insertvalue,
            block.instructions,
            block.name,
        ))

    def total(self, attr: str) -> int:
        return sum(getattr(block, attr) for block in self.blocks)


def parse_ir(path: Path) -> dict[str, Function]:
    functions: dict[str, Function] = {}
    current_name: str | None = None
    function_lines: list[str] = []
    blocks: list[Block] = []
    block_name = 'entry'
    block_lines: list[str] = []

    for raw in path.read_text(errors='replace').splitlines():
        if current_name is None:
            match = DEFINE_RE.match(raw)
            if match:
                current_name = match.group(1) or match.group(2)
                function_lines = [raw]
                blocks = []
                block_name = 'entry'
                block_lines = []
            continue

        function_lines.append(raw)
        stripped = raw.strip()
        label = LABEL_RE.match(stripped)
        if label:
            if block_lines:
                blocks.append(Block(block_name, tuple(block_lines)))
            block_name = label.group(1)
            block_lines = []
        elif stripped == '}':
            if block_lines:
                blocks.append(Block(block_name, tuple(block_lines)))
            if not blocks:
                blocks.append(Block('entry', ()))
            functions[current_name] = Function(
                current_name, '\n'.join(function_lines) + '\n', tuple(blocks))
            current_name = None
        else:
            block_lines.append(raw)
    return functions


def ir_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(path for path in root.rglob('*.ll') if path.is_file())


def census(root: Path, frame_only: bool) -> int:
    files = ir_files(root)
    if not files:
        print(f'error: no LLVM IR files under {root}', file=sys.stderr)
        return 1
    parsed = [(path, parse_ir(path)) for path in files]
    if not any(functions for _, functions in parsed):
        print(f'error: no LLVM functions under {root}', file=sys.stderr)
        return 1
    print(
        'file\tfunction\tlargest_block\tlargest_instructions\t'
        'init_block\tinit_instructions\tinit_insertvalue\tinit_slot_empty\t'
        'init_memset\tinit_memcpy\tinit_stores')
    for path, functions in parsed:
        rel = path.name if root.is_file() else str(path.relative_to(root))
        for function in sorted(functions.values(), key=lambda fn: fn.name):
            largest = function.largest
            candidate = function.init_candidate
            if frame_only and not (
                function.total('slot_empty') or function.total('memset')
            ):
                continue
            print('\t'.join(map(str, (
                rel, function.name, largest.name, largest.instructions,
                candidate.name, candidate.instructions, candidate.insertvalue,
                candidate.slot_empty, candidate.memset, candidate.memcpy,
                candidate.stores,
            ))))
    return 0


def function_map(root: Path) -> dict[tuple[str, str], Function]:
    result: dict[tuple[str, str], Function] = {}
    for path in ir_files(root):
        rel = '' if root.is_file() else str(path.relative_to(root))
        for name, function in parse_ir(path).items():
            result[(rel, name)] = function
    return result


def classify(before: Function | None, after: Function | None) -> str:
    if before is None:
        return 'added'
    if after is None:
        return 'removed'
    bi = before.total('insertvalue')
    ai = after.total('insertvalue')
    bs = before.total('slot_empty')
    ass = after.total('slot_empty')
    am = after.total('memset')
    ac = after.total('memcpy')
    if (ai < bi or ass < bs) and am:
        return 'frame-init-zero-fill'
    if ai < bi and ac:
        return 'destination-materialization'
    if ai != bi or ass != bs or am != before.total('memset'):
        return 'aggregate-lowering'
    return 'other'


def compare(before_root: Path, after_root: Path) -> int:
    before = function_map(before_root)
    after = function_map(after_root)
    if not before or not after:
        print("error: both inputs must contain LLVM functions", file=sys.stderr)
        return 1
    keys = sorted(set(before) | set(after))
    print('file\tfunction\tclass\tbefore_insertvalue\tafter_insertvalue\tbefore_slot_empty\tafter_slot_empty\tbefore_memset\tafter_memset\tbefore_instructions\tafter_instructions')
    for key in keys:
        old = before.get(key)
        new = after.get(key)
        if old is not None and new is not None and old.digest == new.digest:
            continue
        values = (
            key[0], key[1], classify(old, new),
            old.total('insertvalue') if old else 0,
            new.total('insertvalue') if new else 0,
            old.total('slot_empty') if old else 0,
            new.total('slot_empty') if new else 0,
            old.total('memset') if old else 0,
            new.total('memset') if new else 0,
            sum(b.instructions for b in old.blocks) if old else 0,
            sum(b.instructions for b in new.blocks) if new else 0,
        )
        print('\t'.join(map(str, values)))
    return 0


def check(root: Path, max_block_insertvalue: int,
          max_block_slot_empty: int | None, require_memset: bool) -> int:
    worst: tuple[int, str, str, str] = (0, '', '', '')
    worst_slot: tuple[int, str, str, str] = (0, '', '', '')
    memsets = 0
    files = ir_files(root)
    if not files:
        print(f'error: no LLVM IR files under {root}', file=sys.stderr)
        return 1
    function_count = 0
    for path in files:
        rel = path.name if root.is_file() else str(path.relative_to(root))
        for function in parse_ir(path).values():
            function_count += 1
            memsets += function.total('memset')
            for block in function.blocks:
                row = (block.insertvalue, rel, function.name, block.name)
                if row > worst:
                    worst = row
                slot_row = (block.slot_empty, rel, function.name, block.name)
                if slot_row > worst_slot:
                    worst_slot = slot_row
    if function_count == 0:
        print(f'error: no LLVM functions under {root}', file=sys.stderr)
        return 1
    print(f'files={len(files)} max_block_insertvalue={worst[0]} '
          f'at={worst[1]}:{worst[2]}:{worst[3]} '
          f'max_block_slot_empty={worst_slot[0]} '
          f'at={worst_slot[1]}:{worst_slot[2]}:{worst_slot[3]} '
          f'memsets={memsets}')
    failed = worst[0] > max_block_insertvalue
    if (max_block_slot_empty is not None
            and worst_slot[0] > max_block_slot_empty):
        failed = True
    if require_memset and memsets == 0:
        print('error: no llvm.memset call found', file=sys.stderr)
        failed = True
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    census_parser = sub.add_parser('census')
    census_parser.add_argument('root', type=Path)
    census_parser.add_argument('--frame-only', action='store_true')
    compare_parser = sub.add_parser('compare')
    compare_parser.add_argument('before', type=Path)
    compare_parser.add_argument('after', type=Path)
    check_parser = sub.add_parser('check')
    check_parser.add_argument('root', type=Path)
    check_parser.add_argument('--max-block-insertvalue', type=int, default=512)
    check_parser.add_argument('--max-block-slot-empty', type=int)
    check_parser.add_argument('--require-memset', action='store_true')
    args = parser.parse_args()
    if args.command == 'census':
        return census(args.root, args.frame_only)
    if args.command == 'compare':
        return compare(args.before, args.after)
    return check(args.root, args.max_block_insertvalue,
                 args.max_block_slot_empty, args.require_memset)


if __name__ == '__main__':
    raise SystemExit(main())
