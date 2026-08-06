"""Target facts the FRONT END needs (design 47; DF-137d / DF-140a).

Platform `Int`/`UInt` are pointer-width, so what a bare integer literal means
depends on the target: `0x80000000` fits a 64-bit `Int` and overflows a 32-bit
one. The literal range check therefore has to know the EFFECTIVE triple, which
until now only codegen did — so `let x: Int = 0x80000000` compiled clean for
riscv32 and silently wrapped to a negative number.

Codegen derives the width from its module's LLVM data layout
(`CodeGenerator._pointer_size_bits`). The typechecker runs before any module
exists, so it asks LLVM for the triple's data layout directly. Results are
cached: creating a target machine is not free, and one compile asks repeatedly.
"""

import re
from typing import Dict, Optional

_WIDTH_CACHE: Dict[str, int] = {}


def _pointer_size_bits(data_layout: str) -> int:
    """The address-space-0 pointer size (bits) named by an LLVM data layout.

    A pointer spec is `p[<addrspace>]:<size>:<abi>[:<pref>]`; address space 0 is
    written `p:` or `p0:` (riscv32 uses `p:32:32`). Other address spaces (x86's
    `p270:32:32` segment selectors) are ignored. LLVM defaults to 64 when no
    as-0 spec is present, which is what every 64-bit hosted triple relies on.

    Kept identical to `CodeGenerator._pointer_size_bits` on purpose: the front
    end and the back end must agree about what platform `Int` is, or a literal
    the checker accepted would still wrap.
    """
    for spec in data_layout.split('-'):
        m = re.match(r'^p(\d*):(\d+)', spec)
        if m and m.group(1) in ('', '0'):
            return int(m.group(2))
    return 64


def platform_int_width(target_triple: Optional[str] = None) -> int:
    """Platform `Int`/`UInt` width in bits for `target_triple` (default host).

    Falls back to 64 if LLVM cannot describe the triple. A wrong-but-plausible
    width would silently change which literals are legal, so the fallback is the
    host default rather than a guess derived from the triple string.
    """
    from llvmlite import binding

    key = target_triple or ""
    cached = _WIDTH_CACHE.get(key)
    if cached is not None:
        return cached

    width = 64
    try:
        # Targets are not registered until something asks for them. The front end
        # runs BEFORE the CodeGenerator does this, so it has to register them
        # itself — otherwise every triple raises "no targets are registered" and
        # falls back to 64, which is exactly the bug this check exists to catch.
        binding.initialize_native_target()
        binding.initialize_native_asmprinter()
        binding.initialize_all_targets()
        triple = target_triple or binding.get_default_triple()
        target = binding.Target.from_triple(triple)
        machine = target.create_target_machine()
        width = _pointer_size_bits(str(machine.target_data))
    except Exception:
        width = 64

    _WIDTH_CACHE[key] = width
    return width
