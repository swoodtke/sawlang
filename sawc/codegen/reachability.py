"""Pre-LLVM reachability strip (design 168 unit 2).

Codegen used to emit a body for EVERY non-generic function and extension method
the compilation unit loaded, plus every method of every generic extension the
moment a type was instantiated — reachability-blind in both regimes. Since
`import std.x` compiles the whole of `x`, a four-line `hello.saw` emitted 27,922
lines of IR across 449 defines, of which 12 lines were the user's. LLVM then
optimized and object-compiled all of it: design 164 measured the back half at
~64% of every compile, 90.1% of the emitted IR being std.

This module makes emission DEMAND-DRIVEN. Declaration stays eager — every
signature is still created up front, because half of codegen resolves a callee
by a bare `self.functions[name]` lookup with no ensure-call behind it, and a
monomorphization's side effects (`struct_types`, `mono_struct_args`,
`method_defaults`) are what later bodies read. Only the BODY is deferred, behind
the symbol it will define; a body is generated when something the program
actually emits refers to that symbol.

WHY THE REFERENCE SCAN IS THE ORACLE, and not an AST walk of the call graph.
The brief's soundness rule is "when in doubt, keep": an over-kept symbol costs
bytes that unit 1's link dead-strip removes anyway, while an over-stripped one
is a link failure. An AST-level reachability walk would have to re-derive what
codegen does — overload resolution, trait dispatch, drop glue, auto-derived
conformances, closure and trampoline synthesis, the coroutine transform's
callees — and every gap in that re-derivation is an over-strip. Reading the
EMITTED IR instead inverts the risk: a symbol is kept because emitted code
mentions it, so the only way to lose a body is for nothing in the program to
name it. The scan is textual for the same reason — llvmlite erases a constant
bitcast into a `FormattedConstant` whose payload is a plain string, so an object
walk has blind spots that the rendered text does not. A false positive (a string
literal that happens to contain `@main`) over-keeps, which is free.

The fixpoint also owns the `_pending_vtables` queue, which is fed from inside
body generation: filling a vtable emits a thunk that calls the concrete impl, so
a vtable PULLS its methods, which is the direction that makes over-stripping
structurally impossible for dynamic dispatch. It used to own a second queue,
`pending_method_bodies`, which was how a monomorphized method body got emitted;
design 218 unit 1.5 stage 3c-2c retired it — an instance is a spliced concrete
method now, deferred behind its own symbol like any other.
"""

import re

from llvmlite import ir


# An LLVM global reference: `@name`, or `@"quoted name"` when the identifier
# needs escaping. Saw's mangled symbols are ASCII (`$`, `.` and `_` are all
# plain identifier characters in LLVM), so the quoted form is rare, but match it
# rather than assume.
_SYMBOL_REF = re.compile(r'@(?:"((?:[^"\\]|\\.)*)"|([-a-zA-Z$._][-a-zA-Z$._0-9]*))')


class ReachabilityMixin:
    """Deferred body emission + the reachability fixpoint.

    Methods:
        _init_reachability: set up the registry (called from CodeGenerator.__init__)
        _defer_body: register one body generator behind its LLVM symbol
        _root_symbol: mark a symbol reachable regardless of references
        _emit_bodies: run the fixpoint (or, with the strip off, emit everything)
    """

    def _init_reachability(self, strip: bool):
        # Insertion-ordered: with the strip OFF the registry is drained in
        # registration order, which reproduces the old eager passes exactly.
        self._deferred_bodies: dict[str, object] = {}
        self._reachable_symbols: set[str] = set()
        self._scanned_symbols: set[str] = set()
        self._strip_unreachable = strip
        # Reported by `sawc -v` and by the design-168 measurement harness.
        self._bodies_deferred = 0
        self._bodies_emitted = 0

    def _defer_body(self, llvm_func, thunk):
        """Register `thunk` as the generator of `llvm_func`'s body.

        Keyed on the llvm.Function's OWN name rather than the mangled name we
        asked for: llvmlite deduplicates a colliding global by suffixing it, and
        the emitted text carries the deduplicated spelling.
        """
        if llvm_func.blocks:
            # Already generated. A type can be monomorphized from more than one
            # path, and re-registering a live body would append a SECOND entry
            # block to it — invalid IR, and silently so.
            return
        name = llvm_func.name
        if name in self._deferred_bodies:
            return
        self._deferred_bodies[name] = thunk
        self._bodies_deferred += 1

    def _root_symbol(self, name: str):
        """Mark a symbol reachable with no reference needed — the entry point,
        an `@export`, an `@section` placement."""
        self._reachable_symbols.add(name)

    def _seed_reachability_roots(self):
        """The symbols a program is entered through, which no emitted
        instruction names.

        `main` is the C entry. An `@export`ed function or static (design 58) is
        callable from outside this compilation unit by definition. An
        `@section(...)` placement exists so the LINKER can find it at a fixed
        address — a vector-table entry nothing calls — so it is a root too.
        """
        if "main" in self.module.globals:
            self._root_symbol("main")
        for global_value in self._exported_llvm_globals:
            self._root_symbol(global_value.name)
        for fn in self.module.functions:
            if getattr(fn, 'section', None):
                self._root_symbol(fn.name)

    def _collect_references(self):
        """Fold every not-yet-read emitted global's symbol references into the
        reachable set.

        A bodyless `declare` and an initializer-less global carry no references
        and are deliberately NOT marked scanned: either may acquire one later,
        and it must be read when it does.
        """
        for gv in list(self.module.globals.values()):
            name = gv.name
            if name in self._scanned_symbols:
                continue
            if isinstance(gv, ir.Function):
                if not gv.blocks:
                    continue
            elif isinstance(gv, ir.GlobalVariable):
                if gv.initializer is None:
                    continue
            self._scanned_symbols.add(name)
            for match in _SYMBOL_REF.finditer(str(gv)):
                quoted, plain = match.group(1), match.group(2)
                self._reachable_symbols.add(plain if quoted is None else quoted)

    def _emit_bodies(self):
        """Emit function bodies: everything, or only what the program reaches."""
        if not self._strip_unreachable:
            self._emit_every_body()
            return
        self._emit_reachable_bodies()

    def _emit_every_body(self):
        """Strip disabled: drain the registry in registration order, which is the
        order the eager passes used, then the two queues as before."""
        while self._deferred_bodies:
            name = next(iter(self._deferred_bodies))
            self._deferred_bodies.pop(name)()
            self._bodies_emitted += 1
        self._emit_pending_vtables()

    def _emit_reachable_bodies(self):
        """The fixpoint: read what has been emitted, emit what it named, repeat.

        Terminates because every iteration that makes progress either removes an
        entry from `_deferred_bodies` or drains a queue, and nothing ever adds a
        symbol back once its body exists.
        """
        while True:
            progressed = False

            self._collect_references()
            # Iterate the registry in insertion order (not the reachable SET's
            # order) so emission order is a function of the sources alone — a
            # set's iteration order is hash-seed dependent and irdet would see it.
            for name in list(self._deferred_bodies):
                if name in self._reachable_symbols:
                    self._deferred_bodies.pop(name)()
                    self._bodies_emitted += 1
                    progressed = True

            # The vtable queue is fed from inside body generation. A vtable fill
            # emits thunks that CALL their impls, so the next scan pulls those
            # impl bodies in — dispatch can never lose a method.
            if self._pending_vtables:
                self._emit_pending_vtables()
                progressed = True

            if not progressed:
                return
