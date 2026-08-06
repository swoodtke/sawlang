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


def has_native_atomics(target_triple: Optional[str] = None,
                       target_features: Optional[str] = None) -> bool:
    """Whether the target lowers a word-size atomic RMW to a real INSTRUCTION.

    `SpinLock` (design 149 unit d) needs this to be true: its whole
    implementation is a compare-and-swap loop, and where the backend expands
    that into `__atomic_*` libcalls the lock is a call into a C runtime that a
    freestanding kernel does not have — and, if one is supplied, is itself
    usually implemented with a lock. Saying so is a teaching error; falling back
    silently would hand somebody a lock that does not lock.

    The rule is deliberately narrow. RISC-V is the one target in play whose base
    ISA omits atomics, so `--target-features +a` is what answers the question for
    it. Every other architecture Saw targets has word-size atomics in its base
    ISA and answers yes. An ISA string in the triple's arch field (`riscv32imac`,
    or `riscv64gc` — `G` means `IMAFD`) is read too, for the LLVM builds that
    accept one; the diagnostic names only the flag, which every build accepts.
    """
    triple = (target_triple or "").lower()
    if not triple:
        from llvmlite import binding
        try:
            triple = binding.get_default_triple().lower()
        except Exception:
            return True
    arch = triple.split('-')[0]
    if not arch.startswith("riscv"):
        return True

    # An explicit feature wins over the triple, and the LAST mention wins over
    # an earlier one (`+a,-a` disables), matching how LLVM reads the list.
    verdict = None
    for feat in (target_features or "").lower().split(','):
        feat = feat.strip()
        if feat in ('+a', 'a'):
            verdict = True
        elif feat == '-a':
            verdict = False
    if verdict is not None:
        return verdict

    isa = arch[len("riscv"):]
    if isa[:2] in ("32", "64"):
        isa = isa[2:]
    return 'a' in isa or 'g' in isa


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
