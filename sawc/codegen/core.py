"""
Saw Language Code Generator
Generates LLVM IR from the AST using llvmlite.
"""

from typing import Optional, List
from llvmlite import ir, binding
from ast_nodes import (
    Program, Function, Block, Statement, Expression,
    LetStatement, AssignStatement, ReturnStatement, ExpressionStatement,
    WhileExpr, BreakStatement, ContinueStatement, ForLoop, RangeExpr,
    IntLiteral, FloatLiteral, BoolLiteral, StringLiteral, StringInterpolation, Identifier,
    BinaryOp, UnaryOp, MoveExpr, ReferenceExpr, CastExpr, FunctionCall, IfExpr, IfLetExpr,
    TupleLiteral, TupleIndex, ArrayLiteral, ArrayIndex,
    MemberAccess, StructInit,
    NoneLiteral, ForceUnwrap, NilCoalesce, OptionalChain,
    TryExpr, TryCatchExpr,
    GuardLetStatement,
    Struct, StructField,
    Enum, EnumVariant, EnumInit, MatchExpr, MatchArm,
    Extension, Method, MethodCall, SelfExpr,
    SawType, TypeKind, Argument, TypeParameter, TypeDefinition,
    ExternFunction, ExternBlock,
    ClosureExpr
)
from namespace import Namespace


class StaticAssertError(Exception):
    """A failed (or non-constant) `static_assert` (design 53). Surfaced as a
    clean compile error by the codegen driver, not an internal-error trace."""
    def __init__(self, message: str, line: int, column: int):
        super().__init__(message)
        self.message = message
        self.line = line
        self.column = column


from .types import TypesMixin
from .resources import ResourcesMixin
from .generics import GenericsMixin
from .closures import ClosuresMixin
from .optionals import OptionalsMixin
from .conditionals import ConditionalsMixin
from .loops import LoopsMixin
from .methods import MethodsMixin
from .statements import StatementsMixin
from .operators import OperatorsMixin
from .calls import CallsMixin
from .collections import CollectionsMixin
from .structs import StructsMixin
from .match import MatchMixin
from .results import ResultsMixin
from .existentials import ExistentialsMixin
from .debuginfo import DebugInfoMixin
import copy


def _install_volatile_ir_support():
    """Teach llvmlite's textual IR to render `volatile` on loads/stores.

    llvmlite 0.48 has no first-class volatile flag: `builder.load`/`store` emit a
    plain `load`/`store`. design 46 needs volatile MMIO accesses that survive the
    O1 pipeline, so we honor a per-instruction `.volatile = True` by splicing the
    keyword into the rendered instruction. The bit is then set on the real LLVM
    instruction when `binding.parse_assembly` re-reads the text, and every opt
    pass preserves it (the not-elided oracle). Idempotent; applied once at import.
    """
    from llvmlite.ir import instructions as _instrs
    if getattr(_instrs.LoadInstr, "_saw_volatile_patched", False):
        return
    _orig_load = _instrs.LoadInstr.descr
    _orig_store = _instrs.StoreInstr.descr

    def _load_descr(self, buf):
        tmp = []
        _orig_load(self, tmp)
        s = "".join(tmp)
        if getattr(self, "volatile", False):
            s = s.replace("load ", "load volatile ", 1)
        buf.append(s)

    def _store_descr(self, buf):
        tmp = []
        _orig_store(self, tmp)
        s = "".join(tmp)
        if getattr(self, "volatile", False):
            s = s.replace("store ", "store volatile ", 1)
        buf.append(s)

    _instrs.LoadInstr.descr = _load_descr
    _instrs.StoreInstr.descr = _store_descr
    _instrs.LoadInstr._saw_volatile_patched = True


_install_volatile_ir_support()


class CodeGenerator(ResultsMixin, MatchMixin, StructsMixin, CollectionsMixin, CallsMixin, OperatorsMixin, StatementsMixin, MethodsMixin, LoopsMixin, ConditionalsMixin, OptionalsMixin, ClosuresMixin, GenericsMixin, ExistentialsMixin, TypesMixin, ResourcesMixin, DebugInfoMixin):
    def __init__(self, namespace: Namespace, target_triple: Optional[str] = None,
                 freestanding: bool = False, source_path: Optional[str] = None,
                 runtime_build: bool = False):
        # Unified namespace from type checker (Phase 0 of module system)
        self.namespace = namespace

        # Profile flag (design 19/20): freestanding emits the runtime seams as
        # declarations only (no hosted libc-backed defaults) and gates hosted
        # facilities (Float printing, hosted std modules).
        self.freestanding = freestanding

        # Runtime-build mode (design 113b): this module IS a per-host runtime —
        # it `@export`s the `__saw_rt_*` seam bodies. So the compiler emits the
        # seams as DECLARATIONS only (the module's own `@export` definitions
        # collapse into them via the design-58 declaration/definition unify), and
        # every non-exported definition is internalized so the runtime object
        # carries only its exported seams (+ their private helpers) — no
        # duplicate `__saw_string_*`/argv symbols across the runtime + the user
        # program at link time.
        self.runtime_build = runtime_build
        # The seams are declaration-only whenever the compiler is NOT the one
        # providing their bodies: the freestanding profile (environment supplies
        # them) and the runtime-build mode (the Saw runtime provides them).
        self._seams_external_only = freestanding or runtime_build

        # LLVM core init is automatic; targets still need explicit registration.
        # Registering ALL targets (not just the native one) is what lets
        # `--target <triple>` cross-compile: without it, a non-host triple such
        # as x86_64-unknown-none-elf reports "no available targets" (verified
        # against llvmlite 0.48).
        binding.initialize_native_target()
        binding.initialize_native_asmprinter()
        binding.initialize_all_targets()
        binding.initialize_all_asmprinters()

        # Resolve the target triple: default (host) unless --target overrides it.
        self.triple = target_triple or binding.get_default_triple()
        self._explicit_target = target_triple is not None

        # Create module in a FRESH llvmlite context (not the process-global one).
        # llvmlite's `ir.Module` defaults to a module-level singleton
        # `context.global_context`, whose `identified_types` registry caches
        # every named struct type (`get_identified_type`) for the life of the
        # process. In a one-shot `sawc` invocation that is harmless, but a
        # long-lived process that compiles more than once in-process (the design
        # 115 persistent test-worker; a future compile-server/LSP) would hit
        # "<StructName> is already defined" on the SECOND compile when it
        # re-registers a builtin/std identified type (e.g. `Device`). Isolating
        # each compile in its own `ir.Context` makes the identified-type registry
        # per-compile, so re-entrant compiles are independent.
        self.module = ir.Module(name="__saw_module", context=ir.Context())
        self.module.triple = self.triple

        # Create target data for sizeof calculations
        target = binding.Target.from_triple(self.triple)
        target_machine = target.create_target_machine()
        self.target_data = binding.create_target_data(str(target_machine.target_data))
        # Pin the module data layout to the target machine's, ALWAYS (host and
        # cross alike). Without it the module carries an empty datalayout, and the
        # O1 pipeline then computes struct field offsets from LLVM's *generic*
        # default layout while object emission uses the real target layout — a
        # silent disagreement for any struct whose field offsets differ between
        # the two (e.g. an `i1` followed by an aggregate containing an `i64`, as
        # in a coroutine frame `{ i1, { i1, T }, i64, i64 }`). The optimized IR
        # then reads/writes a field at the wrong byte offset (the coroutine state
        # word never advances → the driver loop spins forever). Setting the layout
        # makes optimization and emission agree.
        self.module.data_layout = str(target_machine.target_data)

        # Design 47: Int/UInt are POINTER-WIDTH — 64-bit on x86-64/aarch64,
        # 32-bit on riscv32 (ESP32-P4) — matching Swift's model and the spec's
        # long-standing promise. `self.int_type` is the single derived LLVM type
        # for platform `Int`/`UInt`; every platform-Int lowering (literals,
        # arithmetic + overflow intrinsics, sizeof/alignof/len results, loop
        # induction, Range items, UnsafeMemory addresses) uses it instead of a
        # hardcoded i64. Fixed-width Int8..Int64/UInt8..UInt64 keep their own
        # widths (stable layouts), and the runtime ABI seams (saw_alloc/write/
        # panic sizes, String header + refcount, Arc atomic refcount) stay
        # pinned at i64 — see the audit split in designs/47. The width comes
        # from the target's address-space-0 pointer size in the data layout, so
        # it always agrees with the target machine used for optimization and
        # object emission. Hosted targets are 64-bit, so `int_type is i64` there
        # and every migrated site is byte-identical to the pre-47 compiler.
        self.int_width = self._pointer_size_bits(self.module.data_layout)
        self.int_type = ir.IntType(self.int_width)

        # Builder will be set when generating function bodies
        self.builder: ir.IRBuilder = None

        # Symbol table for variables (name -> alloca instruction)
        self.variables: dict = {}

        # Function table
        self.functions: dict = {}

        # Module-level static globals (design 41): simple name -> LLVM
        # GlobalVariable. Reads of a static load through the matching global.
        self.static_globals: dict = {}

        # Struct types (name -> (LLVM type, field_order))
        self.struct_types: dict = {}
        # Reverse map for monomorphized generic structs: mangled name ->
        # (base struct name, [type_args]). Lets a monomorphized `deinit` body
        # reconstruct its receiver's concrete SawType so appended field cleanup
        # resolves owning fields (e.g. Map's `slots: Vector<..., A>`) through the
        # value's OWN allocator `A`, not a default.
        self.mono_struct_args: dict = {}

        # Enum types (name -> (LLVM type, variant_tags, variant_info))
        # variant_tags: dict[variant_name, tag_value]
        # variant_info: dict[variant_name, list[(param_name, SawType)]]
        self.enum_types: dict = {}

        # String constants (raw C strings: [N x i8] globals for printf etc.)
        self.string_constants: dict = {}
        self.string_counter = 0
        # Saw String literal globals: value -> {i64 refcount(=-1), i64 len, [N+1 x i8]}
        self.string_literal_globals: dict = {}

        # Loop tracking for break/continue
        # Stack of (continue_block, break_block, result_storage) for nested loops
        # result_storage is None for statement context, alloca for expression context
        self.loop_stack: List[tuple] = []

        # Generics support
        # Maps type parameter names to concrete SawTypes during instantiation
        self.type_param_context: dict[str, SawType] = {}
        # Stores original AST of generic functions for later instantiation
        self.generic_functions: dict[str, Function] = {}
        # Stores original AST of generic structs for later instantiation
        self.generic_structs: dict[str, Struct] = {}
        # Stores original AST of generic enums for later instantiation
        self.generic_enums: dict[str, Enum] = {}

        # Self type context - the struct name when generating extension methods
        self.self_type_context: Optional[str] = None
        # Stores original AST of generic extensions for later instantiation
        # Multiple extensions can exist for the same struct (methods + conformances)
        self.generic_extensions: dict[str, List[Extension]] = {}
        # Stores specialized extensions keyed by (struct_name, type_args_tuple)
        # e.g., ("Vector", ("String",)) -> [Extension for Vector<String>]
        self.specialized_extensions: dict[tuple, List[Extension]] = {}
        # Design 40 item 9 (C6): generic METHODS declared on a NON-generic-type
        # extension (e.g. `extension String { func withCString<R>(...) }`).
        # Their type params are unbound until the call site supplies method type
        # args, so they are indexed here (struct_name -> method_name -> Method)
        # and monomorphized on demand rather than declared/generated eagerly.
        self.plain_generic_methods: dict[str, dict[str, Method]] = {}
        # Tracks which monomorphized functions have been generated
        self.generated_instantiations: set[str] = set()
        # Queue for pending method body generation: (mangled_struct_name, method, type_mapping, is_init)
        # Bodies are generated after all signatures are declared
        self.pending_method_bodies: List[tuple] = []

        # Closure counter for unique names
        self.closure_counter = 0

        # Variable types for closure captures (name -> SawType)
        self.variable_types: dict[str, SawType] = {}

        # Default parameter values: mangled_name -> list of default Expression (or None)
        self.method_defaults: dict[str, list] = {}
        # Free-function default parameter values (design 53): the self.functions
        # lookup key -> list of default Expression (or None), one per parameter.
        self.func_defaults: dict[str, list] = {}

        # Resource management: variable lifetime tracking
        # Stack of scopes, each scope is a list of (var_name, saw_type) for variables needing cleanup
        self.cleanup_stack: List[List[tuple[str, SawType]]] = []
        # design 51: `any Trait` existential state (vtables, thunks, destructors).
        self._existential_init()
        # Cache: type_name -> cleanup behavior ('none', 'deinit', 'implicit_copy', 'no_copy')
        self.type_cleanup_behavior: dict[str, str] = {}
        # Cache: canonical type symbol -> whether the aggregate has any field/
        # payload that itself needs cleanup (drop glue for structs that hold
        # cleanup-needing fields but declare no deinit -- e.g. only String fields).
        self.type_field_cleanup: dict[str, bool] = {}
        # Track moved variables - these should not be cleaned up or accessed
        self.moved_variables: set[str] = set()
        # Runtime drop flags (design 42): name -> i1 alloca (1 = still needs drop).
        # A binding that MIGHT be `move`d on some control-flow paths but not others
        # (a conditional move) cannot have its cleanup decided statically — the
        # flat `moved_variables` set would suppress the drop on the not-moved path
        # too, leaking. So a cleanup-registered binding gets a flag, set to 0 at
        # each `move`, and its scope-exit deinit is guarded by the flag: dropped
        # exactly on the paths where it was not moved. Function-local — the alloca
        # belongs to the current llvm function, so this is reset per function and
        # saved/restored around nested (closure/generic) codegen, like `variables`.
        self.drop_flags: dict[str, ir.Value] = {}

        # Statement-scoped temporaries (item 4): owned Deinit-needing values
        # produced mid-statement that are neither bound, returned, nor
        # transferred onward (e.g. the receiver of `makeResource().use()`).
        # None outside a statement; a list (LIFO drop at statement end) while a
        # full statement is being generated. Managed by `_generate_statement`.
        self.statement_temps: Optional[List[tuple]] = None

        # Extern functions that return optionals (need NULL check at call site)
        # Maps function name -> inner SawType (unwrapped from optional)
        self.extern_optional_returns: dict[str, SawType] = {}

        # design 58: `@export`ed functions/statics to anchor against DCE via an
        # `@llvm.used` appending global (emitted once at the end of codegen).
        self._exported_llvm_globals: list = []

        # Current return type (for implicit optional wrapping)
        self.current_return_type: Optional[SawType] = None

        # design 69: DWARF debug-info (line tables). Initialize state now; the
        # module-level metadata (flags + compile unit) is emitted in generate().
        self._di_init(source_path)

        # Declare external functions (printf for print)
        self._declare_external_functions()

    # Built-in type names for detecting specialized extensions
    BUILTIN_TYPE_NAMES = {
        'Int', 'UInt', 'Float', 'Bool', 'String',
        'Int8', 'Int16', 'Int32', 'Int64',
        'UInt8', 'UInt16', 'UInt32', 'UInt64',
    }

    def _get_extension_specialization(self, extension: Extension) -> tuple:
        """Get the specialization key for an extension, or empty tuple if generic.

        Returns tuple of type arg names if specialized (e.g., ("String",)),
        or empty tuple if it's a generic extension.
        """
        if not extension.type_params:
            return ()

        # Check if all type params are known types (specialization)
        type_args = []
        for tp in extension.type_params:
            if tp.name in self.BUILTIN_TYPE_NAMES or tp.name in self.struct_types:
                type_args.append(tp.name)
            else:
                # Not a known type, this is a generic extension
                return ()

        return tuple(type_args)

    def _pad_spec_key_with_defaults(self, struct_name, spec_key, struct_type_params_by_name):
        """Design 37: extend a specialized-extension key with the struct's
        declared trailing default type-arg names, so a spec extension written
        against the default-omitted form matches the fully-applied lookup key.
        `extension Vector<String>` -> `("String", "GlobalAllocator")`."""
        params = struct_type_params_by_name.get(struct_name)
        if not params or len(spec_key) >= len(params):
            return spec_key
        padded = list(spec_key)
        for i in range(len(spec_key), len(params)):
            default = getattr(params[i], 'default', None)
            if (default is None or default.kind != TypeKind.STRUCT
                    or default.struct_name is None):
                break
            padded.append(default.struct_name)
        return tuple(padded)

    def _declare_external_functions(self):
        # Declare printf
        printf_type = ir.FunctionType(
            ir.IntType(32),
            [ir.PointerType(ir.IntType(8))],
            var_arg=True
        )
        self.printf = ir.Function(self.module, printf_type, name="printf")

        # Declare abort for runtime panics
        abort_type = ir.FunctionType(ir.VoidType(), [])
        self.abort = ir.Function(self.module, abort_type, name="abort")

        # Declare snprintf for string formatting
        snprintf_type = ir.FunctionType(
            ir.IntType(32),
            [ir.PointerType(ir.IntType(8)), ir.IntType(64), ir.PointerType(ir.IntType(8))],
            var_arg=True
        )
        self.snprintf = ir.Function(self.module, snprintf_type, name="snprintf")

        # Declare strcpy for string copying
        strcpy_type = ir.FunctionType(
            ir.PointerType(ir.IntType(8)),
            [ir.PointerType(ir.IntType(8)), ir.PointerType(ir.IntType(8))]
        )
        self.strcpy = ir.Function(self.module, strcpy_type, name="strcpy")

        # Declare strcat for string concatenation
        strcat_type = ir.FunctionType(
            ir.PointerType(ir.IntType(8)),
            [ir.PointerType(ir.IntType(8)), ir.PointerType(ir.IntType(8))]
        )
        self.strcat = ir.Function(self.module, strcat_type, name="strcat")

    # _get_llvm_type is now in codegen_types.py (TypesMixin)

    # Resource management methods are now in codegen_resources.py (ResourcesMixin)

    def _entry_alloca(self, llvm_type, name="", align=None):
        """Create an alloca in the current function's entry block.

        `align` overrides the slot's alignment. An enum/Result payload is typed
        `[N x i8]` (ABI align 1), but it is bitcast-and-loaded as the active
        variant's field struct, whose fields (pointers, i64) require 8-alignment;
        a 1-aligned slot lands the payload on an odd offset and the wider load
        alignment-faults on arm64 (a layout-sensitive heisenbug). Payload slots
        therefore pass align=8 so the reinterpreted load is always aligned.

        Every stack slot must be allocated in the entry block, for two reasons:
        - mem2reg/SROA only promote allocas that live in the entry block, so
          entry-block placement is what lets the optimizer lift them into SSA
          registers (see the -O1 pipeline in compile_to_object).
        - An alloca emitted inside a loop body allocates a *fresh* stack slot on
          every iteration; in a hot loop that grows the stack without bound and
          eventually overflows (SIGSEGV). Hoisting to the entry block gives one
          stable slot reused across iterations.

        The builder position is saved and restored, so callers can invoke this
        from anywhere during codegen.
        """
        builder = self.builder
        entry = builder.function.entry_basic_block
        saved_block = builder.block
        if entry.terminator is not None:
            builder.position_before(entry.terminator)
        else:
            builder.position_at_end(entry)
        slot = builder.alloca(llvm_type, name=name)
        if align is not None:
            slot.align = align
        builder.position_at_end(saved_block)
        return slot

    def _create_string_constant(self, value: str) -> ir.GlobalVariable:
        if value in self.string_constants:
            return self.string_constants[value]

        # Add null terminator
        encoded = (value + '\0').encode('utf-8')
        str_type = ir.ArrayType(ir.IntType(8), len(encoded))

        name = f".str.{self.string_counter}"
        self.string_counter += 1

        global_str = ir.GlobalVariable(self.module, str_type, name=name)
        global_str.linkage = 'private'
        global_str.global_constant = True
        global_str.initializer = ir.Constant(str_type, bytearray(encoded))

        self.string_constants[value] = global_str
        return global_str

    # =========================================================================
    # Refcounted String runtime (design 07/11)
    # =========================================================================
    #
    # A `String` value lowers to a single `i8*` pointing at the `bytes` field of
    # a heap block laid out as:
    #
    #     { i64 refcount, i64 len, i8 bytes[len], i8 NUL }
    #
    # The header lives at NEGATIVE offsets from the String pointer (refcount at
    # ptr-16, len at ptr-8). Pointing at `bytes` (not the header) keeps every
    # existing char*-consuming site working unchanged: `s as UnsafePointer<Int8>`
    # is a no-op bitcast, the bytes stay NUL-terminated for FFI, and printf %s
    # reads them directly. String literals use an immortal sentinel refcount of
    # -1 and are never retained/released (a plain load + branch guards every
    # atomic, so literals incur zero atomic traffic).

    @staticmethod
    def _pointer_size_bits(data_layout: str) -> int:
        """Extract the address-space-0 pointer size (bits) from an LLVM data
        layout string — this is the platform `Int`/`UInt` width (design 47).

        The layout is `-`-separated specs; a pointer spec is
        `p[<addrspace>]:<size>:<abi>[:<pref>]`. Address space 0 is written `p:`
        or `p0:` (e.g. riscv32's `p:32:32`); other address spaces (x86's
        `p270:32:32` segment selectors) are ignored. LLVM's default when no
        as-0 pointer spec is present is 64, which is what every 64-bit hosted
        triple relies on (they only override the exotic address spaces).
        """
        import re
        for spec in data_layout.split('-'):
            m = re.match(r'^p(\d*):(\d+)', spec)
            if m and m.group(1) in ('', '0'):
                return int(m.group(2))
        return 64

    def _saw_string_header_ptrs(self, builder, p):
        """Return (block_start_i8ptr, refcount_ptr, len_ptr) for a String bytes
        pointer `p`.

        Design 47: the String header `{ isize refcount, isize len, bytes }` is
        platform-width (the stdlib types `__saw_string_len`/`_alloc` and String's
        refcount protocol as `Int`), so the header is two machine words: refcount
        at `p - 2*wordbytes`, len at `p - wordbytes`. On a 64-bit target this is
        the pre-47 `-16`/`-8`/i64 layout byte-for-byte; on riscv32 it is a
        `-8`/`-4`/i32 header, and the refcount atomics run at the native width.
        """
        i64 = ir.IntType(64)  # GEP byte offsets (index width is immaterial)
        word = self.int_type
        wordptr = word.as_pointer()
        wb = self.int_width // 8
        block = builder.gep(p, [ir.Constant(i64, -2 * wb)], inbounds=True, name="hdr")
        rc_ptr = builder.bitcast(block, wordptr, name="rc_ptr")
        len_raw = builder.gep(p, [ir.Constant(i64, -wb)], inbounds=True)
        len_ptr = builder.bitcast(len_raw, wordptr, name="len_ptr")
        return block, rc_ptr, len_ptr

    def _declare_seams(self):
        """Emit the four runtime seams (design 19 §2, design 20 item 1).

        These are the ONLY runtime boundary between compiled Saw code and the
        environment:
          - saw_alloc(size, align) -> i8*        (global allocator)
          - saw_dealloc(ptr, size, align)        (global deallocator)
          - saw_write(ptr, len)                  (output primitive behind print)
          - saw_panic(msg, len) -> !             (noreturn panic handler)

        Hosted profile (default): emitted as `weak` DEFINITIONS wrapping libc,
        so a user object may override any of them at link time without a flag.
        The hosted defaults deliberately share C stdio (fwrite to stdout) with
        the still-printf-based Float path so print ordering is preserved.

        Freestanding profile: DECLARATIONS only — the user's environment (kernel,
        bootloader, RTOS) provides the definitions at link time.

        Registered in self.functions BEFORE extern blocks and the String runtime
        are declared, so the stdlib's `extern func saw_alloc(...)` declarations
        resolve to these (the extern pass skips names already present) and the
        compiler-emitted allocation helpers can call them directly.
        """
        i8 = ir.IntType(8)
        i8ptr = i8.as_pointer()
        # Design 47: the seam sizes/aligns/lengths are size_t/usize quantities —
        # the stdlib declares them `Int` (e.g. `saw_alloc(size: Int, align: Int)`
        # in std/alloc.saw), so they are platform-width. `i64` below is bound to
        # the platform Int (i64 on hosted, i32 on riscv32); on hosted this is the
        # pre-47 i64 seam ABI byte-for-byte. The hosted libc wrappers (malloc /
        # free / fwrite) take/return size_t, which is likewise pointer-width.
        i64 = self.int_type
        void = ir.VoidType()

        saw_alloc = ir.Function(self.module, ir.FunctionType(i8ptr, [i64, i64]),
                                name="__saw_rt_alloc")
        saw_dealloc = ir.Function(self.module, ir.FunctionType(void, [i8ptr, i64, i64]),
                                  name="__saw_rt_dealloc")
        saw_write = ir.Function(self.module, ir.FunctionType(void, [i8ptr, i64]),
                                name="__saw_rt_write")
        saw_panic = ir.Function(self.module, ir.FunctionType(void, [i8ptr, i64]),
                                name="__saw_rt_panic")
        saw_panic.attributes.add("noreturn")
        # design 45: the cooperative executor's timer seam. `saw_sleep_ms(ms)`
        # parks the current OS thread for `ms` milliseconds (the simplest correct
        # hosted timer). Behind `sleep(ms)` and the entry executor's timed waits;
        # freestanding supplies its own (a WFI/hardware-timer wait).
        saw_sleep_ms = ir.Function(self.module, ir.FunctionType(void, [i64]),
                                   name="__saw_rt_sleep_ms")
        # design 57 (std.time): the monotonic + wall-clock seams. Both return
        # i64. `saw_clock_monotonic_nanos` reads a monotonic clock as nanoseconds
        # since an arbitrary epoch (behind Instant.now()); `saw_unix_timestamp_secs`
        # reads the wall clock as seconds since the Unix epoch. Keeping the
        # struct-timespec layout and the macOS/Linux CLOCK_MONOTONIC constant
        # variance INSIDE the shim (like saw_sleep_ms) is what lets std.time stay
        # pure Saw. Hosted-only (std.time is never imported freestanding).
        saw_clock_monotonic_nanos = ir.Function(
            self.module, ir.FunctionType(i64, []), name="__saw_rt_clock_monotonic_nanos")
        saw_unix_timestamp_secs = ir.Function(
            self.module, ir.FunctionType(i64, []), name="__saw_rt_unix_timestamp_secs")

        self.functions["__saw_rt_alloc"] = saw_alloc
        self.functions["__saw_rt_dealloc"] = saw_dealloc
        self.functions["__saw_rt_write"] = saw_write
        self.functions["__saw_rt_panic"] = saw_panic
        self.functions["__saw_rt_sleep_ms"] = saw_sleep_ms
        self.functions["__saw_rt_clock_monotonic_nanos"] = saw_clock_monotonic_nanos
        self.functions["__saw_rt_unix_timestamp_secs"] = saw_unix_timestamp_secs
        self.saw_write = saw_write
        self.saw_panic = saw_panic

        _seams = (saw_alloc, saw_dealloc, saw_write, saw_panic, saw_sleep_ms,
                  saw_clock_monotonic_nanos, saw_unix_timestamp_secs)
        # design 113b: these seam BODIES are now authored in Saw + shim.c under
        # `sawc/rt/` (common/mem.saw, common/sleep.saw, host_*/clock.saw,
        # shim.c) and linked into hosted builds by rt_build.py; the compiler only
        # DECLARES them (external), exactly as the freestanding profile always
        # did. A user program links the runtime; a `--runtime-build` module's
        # `@export` of the same name collapses into the declaration (design-58
        # unify). No profile synthesizes these bodies in IR anymore.
        for fn in _seams:
            fn.linkage = "external"

    def _is_apple_triple(self) -> bool:
        t = (self.triple or "").lower()
        return "apple" in t or "darwin" in t or "macos" in t or "ios" in t

    def _declare_print_runtime(self):
        """Emit __saw_print_int: format a signed platform-width integer as decimal
        plus a trailing newline, then emit it with a single saw_write.

        This replaces printf("%lld\\n", n) for the whole integer family. The value
        is formatted at the platform Int width (`self.int_type`) — design 47.
        Callers first bring the value to that width with exactly the sign-/zero-
        extension the old printf path used (sext for signed, zext for unsigned
        narrower than the word), so on a 64-bit target the argument matches
        %lld's bit-for-bit and formatting reproduces printf output byte-for-byte
        across the full i64 range, INT64_MIN included. Formatting at the platform
        width is also what keeps this libcall-free on riscv32: the digit-extract
        udiv/urem run at 32 bits (native), never pulling __udivdi3.

        MIN handling: the magnitude is computed as an *unsigned* value
        (`select(neg, 0 - n, n)` — the wrapping negation of the signed minimum is
        itself, which read unsigned is its magnitude), and digits are extracted
        with unsigned udiv/urem, so no signed overflow occurs.
        """
        i8 = ir.IntType(8)
        i8ptr = i8.as_pointer()
        i64 = ir.IntType(64)        # pointer arithmetic offsets (structural)
        iw = self.int_type          # platform Int width (the value being formatted)
        void = ir.VoidType()

        fn = ir.Function(self.module, ir.FunctionType(void, [iw]),
                         name="__saw_print_int")
        self.functions["__saw_print_int"] = fn
        n = fn.args[0]; n.name = "n"

        entry = fn.append_basic_block("entry")
        loop = fn.append_basic_block("loop")
        after = fn.append_basic_block("after")
        b = ir.IRBuilder(entry)
        # 24 bytes: up to 20 digits/sign for i64 + newline + slack.
        buf = b.alloca(ir.ArrayType(i8, 24), name="buf")
        bufp = b.gep(buf, [ir.Constant(i64, 0), ir.Constant(i64, 0)], inbounds=True)
        endp = b.gep(bufp, [ir.Constant(i64, 24)], inbounds=True, name="end")
        nlpos = b.gep(endp, [ir.Constant(i64, -1)], inbounds=True, name="nlpos")
        b.store(ir.Constant(i8, ord('\n')), nlpos)
        neg = b.icmp_signed('<', n, ir.Constant(iw, 0), name="neg")
        mag = b.select(neg, b.sub(ir.Constant(iw, 0), n), n, name="mag")
        b.branch(loop)

        b = ir.IRBuilder(loop)
        m = b.phi(iw, name="m")
        writep = b.phi(i8ptr, name="writep")
        m.add_incoming(mag, entry)
        writep.add_incoming(nlpos, entry)
        digit = b.urem(m, ir.Constant(iw, 10), name="digit")
        ch = b.trunc(b.add(digit, ir.Constant(iw, ord('0'))), i8, name="ch")
        newwritep = b.gep(writep, [ir.Constant(i64, -1)], inbounds=True, name="w")
        b.store(ch, newwritep)
        m2 = b.udiv(m, ir.Constant(iw, 10), name="m2")
        m.add_incoming(m2, loop)
        writep.add_incoming(newwritep, loop)
        done = b.icmp_unsigned('==', m2, ir.Constant(iw, 0), name="done")
        b.cbranch(done, after, loop)

        b = ir.IRBuilder(after)
        # newwritep points at the most significant digit. Prepend '-' if negative.
        signp = b.gep(newwritep, [ir.Constant(i64, -1)], inbounds=True, name="signp")
        b.store(ir.Constant(i8, ord('-')), signp)
        startp = b.select(neg, signp, newwritep, name="startp")
        # saw_write takes a platform-width length (design 47), so measure at iw.
        length = b.sub(b.ptrtoint(endp, iw), b.ptrtoint(startp, iw), name="len")
        b.call(self.functions["__saw_rt_write"], [startp, length])
        b.ret_void()

    def _declare_string_runtime(self):
        """Emit the refcounted-String runtime helpers and the compiler-known
        String.copy()/String.deinit() bodies the resource machinery calls.

        Must run before extern blocks are declared so the stdlib's `extern`
        declarations of __saw_string_* resolve to these definitions (the extern
        pass skips names already defined) while still registering their
        optional-return wrapping.
        """
        i8 = ir.IntType(8)
        i8ptr = i8.as_pointer()
        i64 = ir.IntType(64)   # pointer-arithmetic GEP byte offsets (index width)
        # Design 47: the String header `{ isize refcount, isize len, bytes }` is
        # platform-width — the stdlib types `__saw_string_len`/`_alloc`/refcount
        # as `Int` — so refcount, len, and allocation sizes use `word`, and the
        # header spans two machine words (`hb` = header bytes). Hosted (word=i64,
        # hb=16) reproduces the pre-47 layout byte-for-byte.
        word = self.int_type
        wb = self.int_width // 8      # bytes per machine word
        hb = 2 * wb                   # header bytes (refcount + len)
        void = ir.VoidType()
        null = ir.Constant(i8ptr, None)

        # String buffers now route through the seams (design 20 item 1) rather
        # than libc malloc/free directly. memcpy stays a libc/compiler builtin
        # (it is not a seam and is available freestanding via compiler-rt).
        saw_alloc_fn = self.functions["__saw_rt_alloc"]
        saw_dealloc_fn = self.functions["__saw_rt_dealloc"]
        memcpy_fn = self._libc_func("memcpy", i8ptr, [i8ptr, i8ptr, word])
        align16 = ir.Constant(word, 16)

        # ---- __saw_string_retain(i8* s) -------------------------------------
        fn = ir.Function(self.module, ir.FunctionType(void, [i8ptr]),
                         name="__saw_string_retain")
        self.functions["__saw_string_retain"] = fn
        s = fn.args[0]; s.name = "s"
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        with b.if_then(b.icmp_unsigned('!=', s, null)):
            _, rc_ptr, _ = self._saw_string_header_ptrs(b, s)
            rc = b.load(rc_ptr, name="rc")  # plain load: immortal check first
            with b.if_then(b.icmp_signed('!=', rc, ir.Constant(word, -1))):
                # a live reference keeps the object alive; relaxed is enough
                b.atomic_rmw('add', rc_ptr, ir.Constant(word, 1), ordering='monotonic')
        b.ret_void()

        # ---- __saw_string_release(i8* s) ------------------------------------
        fn = ir.Function(self.module, ir.FunctionType(void, [i8ptr]),
                         name="__saw_string_release")
        self.functions["__saw_string_release"] = fn
        s = fn.args[0]; s.name = "s"
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        with b.if_then(b.icmp_unsigned('!=', s, null)):
            block, rc_ptr, _ = self._saw_string_header_ptrs(b, s)
            rc = b.load(rc_ptr, name="rc")  # plain load: immortal check first
            with b.if_then(b.icmp_signed('!=', rc, ir.Constant(word, -1))):
                old = b.atomic_rmw('sub', rc_ptr, ir.Constant(word, 1),
                                   ordering='release')
                with b.if_then(b.icmp_signed('==', old, ir.Constant(word, 1))):
                    # last owner observed count->0: order every other thread's
                    # final reads before the free, then free the whole block.
                    b.fence(ordering='acquire')
                    # dealloc size = header (hb) + len + 1 (NUL); len lives at
                    # ptr-wb, so it is always available at the free site.
                    _, _, len_ptr = self._saw_string_header_ptrs(b, s)
                    slen = b.load(len_ptr, name="len")
                    total = b.add(slen, ir.Constant(word, hb + 1), name="dealloc_size")
                    b.call(saw_dealloc_fn, [block, total, align16])
        b.ret_void()

        # ---- __saw_string_alloc(word len) -> i8*  (NULL on OOM) -------------
        fn = ir.Function(self.module, ir.FunctionType(i8ptr, [word]),
                         name="__saw_string_alloc")
        self.functions["__saw_string_alloc"] = fn
        length = fn.args[0]; length.name = "len"
        entry = fn.append_basic_block("entry")
        oom = fn.append_basic_block("oom")
        ok = fn.append_basic_block("ok")
        b = ir.IRBuilder(entry)
        total = b.add(length, ir.Constant(word, hb + 1), name="total")  # hdr + len + NUL
        block = b.call(saw_alloc_fn, [total, align16], name="block")
        b.cbranch(b.icmp_unsigned('==', block, null), oom, ok)
        b = ir.IRBuilder(oom)
        b.ret(null)
        b = ir.IRBuilder(ok)
        wordptr = word.as_pointer()
        rc_ptr = b.bitcast(block, wordptr, name="rc_ptr")
        b.store(ir.Constant(word, 1), rc_ptr)
        len_raw = b.gep(block, [ir.Constant(i64, wb)], inbounds=True)
        len_ptr = b.bitcast(len_raw, wordptr, name="len_ptr")
        b.store(length, len_ptr)
        bytes_ptr = b.gep(block, [ir.Constant(i64, hb)], inbounds=True, name="bytes")
        nul_ptr = b.gep(bytes_ptr, [length], inbounds=True, name="nul")
        b.store(ir.Constant(i8, 0), nul_ptr)
        b.ret(bytes_ptr)

        # ---- __saw_string_from_bytes(i8* src, word len) -> i8* --------------
        fn = ir.Function(self.module, ir.FunctionType(i8ptr, [i8ptr, word]),
                         name="__saw_string_from_bytes")
        self.functions["__saw_string_from_bytes"] = fn
        src = fn.args[0]; src.name = "src"
        length = fn.args[1]; length.name = "len"
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        bytes_ptr = b.call(self.functions["__saw_string_alloc"], [length], name="dst")
        with b.if_then(b.icmp_unsigned('!=', bytes_ptr, null)):
            b.call(memcpy_fn, [bytes_ptr, src, length])
        b.ret(bytes_ptr)

        # ---- __saw_string_len(i8* s) -> word --------------------------------
        fn = ir.Function(self.module, ir.FunctionType(word, [i8ptr]),
                         name="__saw_string_len")
        self.functions["__saw_string_len"] = fn
        s = fn.args[0]; s.name = "s"
        entry = fn.append_basic_block("entry")
        null_b = fn.append_basic_block("is_null")
        ok = fn.append_basic_block("ok")
        b = ir.IRBuilder(entry)
        b.cbranch(b.icmp_unsigned('==', s, null), null_b, ok)
        b = ir.IRBuilder(null_b)
        b.ret(ir.Constant(word, 0))
        b = ir.IRBuilder(ok)
        _, _, len_ptr = self._saw_string_header_ptrs(b, s)
        b.ret(b.load(len_ptr, name="len"))

        # ---- String.copy(&self) -> String : retain, return same pointer -----
        fn = ir.Function(self.module, ir.FunctionType(i8ptr, [i8ptr]),
                         name=self._mangle_method_name("String", "copy"))
        self.functions[self._mangle_method_name("String", "copy")] = fn
        s = fn.args[0]; s.name = "self"
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        b.call(self.functions["__saw_string_retain"], [s])
        b.ret(s)

        # ---- String.deinit(&var self) : release ------------------------------
        # Called as deinit(i8** self_slot); load the String pointer and release.
        fn = ir.Function(self.module, ir.FunctionType(void, [i8ptr.as_pointer()]),
                         name=self._mangle_method_name("String", "deinit"))
        self.functions[self._mangle_method_name("String", "deinit")] = fn
        slot = fn.args[0]; slot.name = "self"
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        sval = b.load(slot, name="s")
        b.call(self.functions["__saw_string_release"], [sval])
        b.ret_void()

    def _declare_argv_runtime(self):
        """Command-line argument access, unified across platforms (design 81
        CI rider). The C entry `main(argc, argv)` stashes its two arguments into
        private module globals at startup (see the main prologue in methods.py);
        `Env.argc`/`Env.arg` read them through the accessor seams here on EVERY
        target. This replaces the Apple-only `_NSGetArgc`/`_NSGetArgv` externs,
        which failed to link on Linux.

        `__saw_argv` holds `char**` (the argv value main received); `__saw_argc`
        holds the `i32` count. The accessors are plain loads."""
        i32 = ir.IntType(32)
        i8ptr = ir.IntType(8).as_pointer()
        i8ptrptr = i8ptr.as_pointer()

        argc_g = ir.GlobalVariable(self.module, i32, name="__saw_argc")
        argc_g.linkage = "internal"
        argc_g.initializer = ir.Constant(i32, 0)
        self._argc_global = argc_g

        argv_g = ir.GlobalVariable(self.module, i8ptrptr, name="__saw_argv")
        argv_g.linkage = "internal"
        argv_g.initializer = ir.Constant(i8ptrptr, None)
        self._argv_global = argv_g

        # ---- __saw_get_argc() -> i32 ----------------------------------------
        fn = ir.Function(self.module, ir.FunctionType(i32, []),
                         name="__saw_rt_get_argc")
        self.functions["__saw_rt_get_argc"] = fn
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        b.ret(b.load(argc_g, name="argc"))

        # ---- __saw_get_argv() -> char** -------------------------------------
        fn = ir.Function(self.module, ir.FunctionType(i8ptrptr, []),
                         name="__saw_rt_get_argv")
        self.functions["__saw_rt_get_argv"] = fn
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        b.ret(b.load(argv_g, name="argv"))

    def _declare_atomic_runtime(self):
        """Emit the atomic seams the Arc/Channel refcount protocol needs
        (design 21 item 2; ordering per design 07). These are thin wrappers over
        LLVM atomic ops, exposed to the stdlib as `extern` i64-pointer helpers:

          - __saw_atomic_add_i64(ptr, delta) -> old   (monotonic/relaxed): a live
            reference keeps the object alive, so a retain needs no ordering.
          - __saw_atomic_sub_i64_release(ptr, delta) -> old   (release): the
            releasing thread publishes its writes; the thread that observes the
            count reach zero pairs this with an acquire fence before teardown.
          - __saw_atomic_fence_acquire(): orders every other thread's final
            reads/writes before the deinit + free performed by the last owner.

        Emitted as real definitions BEFORE extern blocks so the stdlib's
        `extern func __saw_atomic_*` declarations resolve to these.

        Design 47: the refcount these operate on is a platform-`Int` counter —
        the stdlib types the seams `(ptr: UnsafePointer<Int>, delta: Int) -> Int`
        and both Arc's control block and Channel's shared block store the count
        as `Int`. So the atomic width follows the platform word (i64 hosted, i32
        riscv32); the `_i64` in the symbol name is historical. A handle count
        never approaches 2^31, and a word-width atomic is the native AMO on the
        target (no forced 64-bit atomic libcall on a 32-bit machine).
        """
        word = self.int_type
        i64 = word           # historical name; the counter is platform-width
        i64ptr = word.as_pointer()
        void = ir.VoidType()

        # __saw_atomic_add_i64(word* ptr, word delta) -> word (old), monotonic
        fn = ir.Function(self.module, ir.FunctionType(i64, [i64ptr, i64]),
                         name="__saw_atomic_add_i64")
        self.functions["__saw_atomic_add_i64"] = fn
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        old = b.atomic_rmw('add', fn.args[0], fn.args[1], ordering='monotonic')
        b.ret(old)

        # __saw_atomic_sub_i64_release(word* ptr, word delta) -> word, release
        fn = ir.Function(self.module, ir.FunctionType(i64, [i64ptr, i64]),
                         name="__saw_atomic_sub_i64_release")
        self.functions["__saw_atomic_sub_i64_release"] = fn
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        old = b.atomic_rmw('sub', fn.args[0], fn.args[1], ordering='release')
        b.ret(old)

        # __saw_atomic_fence_acquire()
        fn = ir.Function(self.module, ir.FunctionType(void, []),
                         name="__saw_atomic_fence_acquire")
        self.functions["__saw_atomic_fence_acquire"] = fn
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        b.fence(ordering='acquire')
        b.ret_void()

    def _static_mangled_name(self, name: str) -> str:
        """The LLVM global name for a static (design 41). Prefixed so it never
        clashes with a like-named function in the shared LLVM value symbol
        table."""
        return f"saw.static.{name}"

    def _type_has_interior_mutability(self, saw_type) -> bool:
        """Whether a static of `saw_type` must be a NON-constant global — i.e. it
        contains an `Atomic` cell somewhere. Immutable POD statics are emitted as
        `global_constant` (rodata-eligible); interior-mutable ones are not."""
        if saw_type is None:
            return False
        if saw_type.kind == TypeKind.STRUCT:
            if saw_type.struct_name == "Atomic":
                return True
            base = saw_type.struct_name
            fields = self.namespace.get_struct_fields(base)
            if fields:
                return any(self._type_has_interior_mutability(ft)
                           for ft in fields.values())
            return False
        if saw_type.kind == TypeKind.ARRAY:
            return self._type_has_interior_mutability(saw_type.array_element_type)
        return False

    def _const_from_expr(self, expr, saw_type):
        """Build an LLVM constant for a static initializer (design 41 item 2).

        Handles exactly the const-init forms the typechecker admits: numeric /
        Bool literals, a negated numeric literal, constant fixed-array literals,
        POD struct literals with constant fields, and `Atomic(<int>)`. `saw_type`
        drives the target LLVM type (widths, aggregate layout).
        """
        from ast_nodes import (IntLiteral, FloatLiteral, BoolLiteral, UnaryOp,
                                ArrayLiteral, StructInit, FunctionCall,
                                SourceLocationLiteral)
        llvm_type = self._get_llvm_type(saw_type)
        if isinstance(expr, IntLiteral):
            return ir.Constant(llvm_type, expr.value)
        # A resolved `#line` literal (design 98) is an Int compile-time constant.
        if isinstance(expr, SourceLocationLiteral):
            return ir.Constant(llvm_type, expr.resolved_int)
        if isinstance(expr, FloatLiteral):
            return ir.Constant(llvm_type, expr.value)
        if isinstance(expr, BoolLiteral):
            return ir.Constant(llvm_type, 1 if expr.value else 0)
        if isinstance(expr, UnaryOp) and expr.op == '-':
            return ir.Constant(llvm_type, -expr.operand.value)
        if isinstance(expr, ArrayLiteral):
            elem_saw = saw_type.array_element_type
            elems = [self._const_from_expr(e, elem_saw) for e in expr.elements]
            return ir.Constant(llvm_type, elems)
        if isinstance(expr, FunctionCall) and getattr(expr, 'is_atomic_construct', False):
            # Atomic<Int> is `{ i64 }`; initialize the value slot.
            val = self._const_from_expr(expr.arguments[0].value, SawType(TypeKind.INT))
            return ir.Constant(llvm_type, [val])
        if isinstance(expr, FunctionCall) and getattr(expr, 'is_unsafe_mem_construct', False):
            # design 46: UnsafeMemory<T, Use> is one word — the raw address. Its
            # LLVM type is i64 (`llvm_type` here), so the const is just the literal.
            return self._const_from_expr(expr.arguments[0].value, SawType(TypeKind.INT))
        if isinstance(expr, StructInit):
            base = saw_type.struct_name
            field_order = self.struct_types[base][1]
            fields = self.namespace.get_struct_fields(base) or {}
            by_name = {n: v for n, v in expr.field_inits}
            elems = [self._const_from_expr(by_name[fn], fields[fn]) for fn in field_order]
            return ir.Constant(llvm_type, elems)
        raise ValueError(f"non-constant static initializer: {type(expr).__name__}")

    def _emit_llvm_used(self):
        """design 58: emit `@llvm.used` listing every `@export`ed function and
        static, so they survive DCE/global-DCE at the default -O1 pipeline even
        when nothing in the compilation unit references them (the `_start` /
        vector-table shape). `@llvm.used` is the linker-agnostic keep-alive
        anchor; external visibility (default linkage) makes the symbol callable
        from C. Emitted once, after all definitions exist."""
        if not self._exported_llvm_globals:
            return
        i8ptr = ir.IntType(8).as_pointer()
        n = len(self._exported_llvm_globals)
        arr_ty = ir.ArrayType(i8ptr, n)
        used = ir.GlobalVariable(self.module, arr_ty, name="llvm.used")
        used.linkage = "appending"
        used.section = "llvm.metadata"
        elems = [g.bitcast(i8ptr) for g in self._exported_llvm_globals]
        used.initializer = ir.Constant(arr_ty, elems)

    def _emit_static_global(self, static):
        """Emit the LLVM global for one module-level static (design 41 item 3).

        Immutable POD statics become `global_constant` globals (rodata); a static
        whose type carries an `Atomic` cell is a mutable global (its cell is
        written in place via atomics). A bare declaration (no initializer) is a
        `zeroinitializer`. Reads resolve through `self.static_globals`.
        """
        from ast_nodes import is_exported, export_symbol, section_name
        exported = is_exported(static)
        c_symbol = export_symbol(static) if exported else None

        llvm_type = self._get_llvm_type(static.type)
        # An @export static takes the exact C data symbol; otherwise the mangled
        # module-local name (design 41).
        gname = c_symbol if c_symbol else self._static_mangled_name(static.name)
        gv = ir.GlobalVariable(self.module, llvm_type, name=gname)
        # Exported statics are externally-visible definitions (default linkage);
        # everything else stays module-local (`internal`).
        gv.linkage = '' if exported else 'internal'

        if static.initializer is None:
            gv.initializer = ir.Constant(llvm_type, None)  # zeroinitializer
        else:
            gv.initializer = self._const_from_expr(static.initializer, static.type)

        # Constant (rodata-eligible) ONLY when the storage is genuinely never
        # written: an interior-mutable static (Atomic cell) is written in place;
        # and a BARE-DECLARED zero-init static is scratch storage a slab (or other
        # raw-pointer-mediated region — design 42) writes through `&STATIC as
        # UnsafePointer<...>`, so it must be a writable `.bss` global, not rodata.
        # Source-level immutability still holds either way — the typechecker
        # rejects `STATIC = ...` / `&var STATIC` regardless of this flag. An
        # INITIALIZED POD static is a true immutable constant (rodata).
        gv.global_constant = (
            static.initializer is not None
            and not self._type_has_interior_mutability(static.type))

        # design 58: an @export static gets a named object-file section (if any)
        # and is anchored against DCE via @llvm.used.
        sec = section_name(static)
        if sec:
            gv.section = sec
        if exported and gv not in self._exported_llvm_globals:
            self._exported_llvm_globals.append(gv)

        self.static_globals[static.name] = gv

    def _declare_pthread_runtime(self):
        """Emit thin pthread wrappers the concurrency stdlib links against
        (design 21 item 4). These exist so the stdlib never has to spell a NULL
        attr pointer at the Saw level (Saw has no null-pointer literal, and an
        optional-pointer extern param would be an ABI mismatch); the wrapper
        passes the platform-correct NULL and forwards the rest.

        pthread symbols resolve from libSystem on macOS and libc/libpthread on
        Linux; clang's default link line pulls them in.

        Task launch (design 21b item 5; consolidated by design 117):
        `__saw_rt_thread_spawn` supplies the NULL attr, takes the trampoline as
        a `i8*(i8*)` start routine plus its env arg, and RETURNS the OS thread
        handle (pointer-sized `pthread_t`). `__saw_rt_thread_join` takes that
        handle BY VALUE (pthread_t is pointer-sized on both macOS and glibc).
        `__saw_rt_thread_spawn` is called by spawn codegen (which holds the
        trampoline `ir.Function`) — it stores the returned handle into the task
        control block's first slot; `__saw_rt_thread_join` is called from
        `Task.join`/`Task.deinit` in std/task.saw.
        """
        i8ptr = ir.IntType(8).as_pointer()
        void = ir.VoidType()

        # Trampoline type: void* start_routine(void* arg). Spawn codegen shapes
        # its trampolines to this and hands them to __saw_rt_pthread_create.
        self.pthread_tramp_type = ir.FunctionType(i8ptr, [i8ptr])
        tramp_ptr_ty = self.pthread_tramp_type.as_pointer()

        # design 113b/117: the thread seam BODIES are authored in Saw + shim.c
        # (common/pthread.saw for mutex/cond init + thread_join; shim.c for
        # thread_spawn — DF-113b, a raw C function pointer). The compiler only
        # DECLARES them (external) and links the runtime; a `--runtime-build`
        # module's `@export` collapses into the declaration (design-58 unify).
        #
        # `__saw_rt_thread_spawn`'s start-routine param: in a user program the
        # spawn codegen passes a real trampoline `ir.Function` (the fn-ptr type);
        # in the runtime-build offload body (offload.saw) the shim's thunk address
        # arrives as a plain `i8*`. Both are pointer-identical at the C ABI (the
        # shim declares `void*(*)(void*)`); pick the param type that matches the
        # caller in this compilation so llvmlite's strict type check is satisfied.
        start_ty = i8ptr if self.runtime_build else tramp_ptr_ty
        word = self.int_type
        # design 117: the thread surface is consolidated to spawn/join.
        # `__saw_rt_thread_spawn(entry, env) -> handle` returns the OS thread
        # handle (a pointer-sized `pthread_t` word) rather than writing a
        # caller slot; `__saw_rt_thread_join(handle)` takes that handle by value.
        # The control-block layout is unchanged — spawn codegen stores the
        # returned handle into the same 8-byte slot pthread_create wrote before.
        decls = [
            ("__saw_rt_pthread_mutex_init_default", ir.FunctionType(void, [i8ptr])),
            ("__saw_rt_pthread_cond_init_default", ir.FunctionType(void, [i8ptr])),
            ("__saw_rt_thread_spawn",
             ir.FunctionType(word, [start_ty, i8ptr])),
            ("__saw_rt_thread_join", ir.FunctionType(void, [word])),
        ]
        for name, fty in decls:
            fn = ir.Function(self.module, fty, name=name)
            fn.linkage = "external"
            self.functions[name] = fn

    def _declare_io_runtime(self):
        """Emit the design-76 IO reactor + nonblocking-socket helper seams.

        The reactor is a process-global kqueue (macOS) / epoll (Linux) fd, created
        lazily and race-safely (an atomic cmpxchg publishes the fd; a loser closes
        its spare). `saw_reactor_register(fd, write, token)` arms one-shot readiness
        interest, carrying `token` as the event's user-data (kevent.udata /
        epoll_event.data) — the PARKED FRAME'S `__wake`-word ADDRESS (design 91).
        `saw_reactor_poll(timeout_ms)` blocks in kevent/epoll_wait up to
        `timeout_ms` (<0 = forever), then for EACH ready event LATCHES its token
        word to 0 (ready) — waking EXACTLY the frame(s) that registered for that
        (fd, direction), not the herd — and returns the ready-event count. The
        latch is a persistent word (not an edge), so even a poll that fires before
        the scheduler has finished recording the park is never lost: the next wake
        scan reads the latched word. Because the token is the frame's own word (per
        PARK, not per fd-number) and EV_ONESHOT + close both drop the registration,
        a reused fd number can never route a wake to a stale frame. The kernel owns
        the interest set, so register/poll are each a single syscall with no
        user-space fd array to manage — this is why kqueue/epoll fits a global
        reactor better than poll(2).

        Many frames on one fd: kqueue/epoll key the interest set by (fd, filter),
        so two frames waiting DIFFERENT directions on one fd are two independent
        registrations, each with its own token — both are woken precisely. Two
        frames waiting the SAME direction on one fd collapse to a single kernel
        registration whose token is the last registrant's — last-writer-wins; the
        retained belt-and-suspenders re-verify keeps that safe. Concurrent
        same-direction waiters on one fd are not a supported pattern.

        The remaining shims keep the OS-divergent socket bits (O_NONBLOCK, the
        EAGAIN/EINPROGRESS errno values, the `struct sockaddr_in` family/len
        layout) INSIDE the compiler — exactly the std.time precedent — so
        std/net.saw can call plain libc `socket`/`bind`/`listen`/`accept`/
        `connect`/`read`/`write`/`close` directly and stay pure Saw.

        Hosted-only: freestanding declares them external (net.saw is never loaded
        freestanding — a kernel supplies its own reactor via interrupts/WFI).
        """
        i8 = ir.IntType(8)
        i8ptr = i8.as_pointer()
        i16 = ir.IntType(16)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void = ir.VoidType()
        apple = self._is_apple_triple()

        # design 117: the reactor is INSTANCE-based. `reactor_create() -> ptr`
        # returns an opaque instance (kqueue/epoll fd + self-wake pipe + poll
        # buffer policy); register/poll/wake/destroy take it. The process-global
        # singleton is executor policy — a compiler-synthesized `__saw_reactor()`
        # lazy getter below — so the ABI functions carry no hidden global state.
        create = ir.Function(self.module, ir.FunctionType(i64, []),
                             name="__saw_rt_reactor_create")
        reg = ir.Function(self.module, ir.FunctionType(void, [i64, i64, i64, i64]),
                          name="__saw_rt_reactor_register")
        poll = ir.Function(self.module, ir.FunctionType(i64, [i64, i64]),
                           name="__saw_rt_reactor_poll")
        # design 102 item 2: the reactor self-wake seam. `reactor_wake(r)` writes
        # one byte to the instance's self-pipe whose read end the reactor poll
        # registers, so a `cancel()` on an already-io-parked task makes the blocked
        # poll return promptly (else an idle-fd park would never observe the cancel).
        wake = ir.Function(self.module, ir.FunctionType(void, [i64]),
                           name="__saw_rt_reactor_wake")
        destroy = ir.Function(self.module, ir.FunctionType(void, [i64]),
                              name="__saw_rt_reactor_destroy")
        setnb = ir.Function(self.module, ir.FunctionType(i64, [i64]),
                            name="__saw_rt_set_nonblocking")
        setfam = ir.Function(self.module, ir.FunctionType(void, [i8ptr]),
                             name="__saw_rt_sin_set_family")
        # design 117: the three errno ACCESSORS (errno / errno_would_block /
        # errno_connect_state) are gone. The host errno -> portable SysError tag
        # mapping is behind one seam; the OS ops carry their own status.
        last_err = ir.Function(self.module, ir.FunctionType(i64, []),
                               name="__saw_rt_last_syserror")
        # design 117: status-carrying network ops (>= 0 success/count, -tag on
        # failure). Read/write take (fd, buf, len); the rest take Int args.
        tcp_listen = ir.Function(self.module, ir.FunctionType(i64, [i64]),
                                 name="__saw_rt_tcp_listen")
        tcp_local_port = ir.Function(self.module, ir.FunctionType(i64, [i64]),
                                     name="__saw_rt_tcp_local_port")
        tcp_accept = ir.Function(self.module, ir.FunctionType(i64, [i64]),
                                 name="__saw_rt_tcp_accept")
        tcp_connect_start = ir.Function(self.module, ir.FunctionType(i64, [i64]),
                                        name="__saw_rt_tcp_connect_start")
        tcp_connect_check = ir.Function(self.module, ir.FunctionType(i64, [i64, i64]),
                                        name="__saw_rt_tcp_connect_check")
        tcp_read = ir.Function(self.module, ir.FunctionType(i64, [i64, i8ptr, i64]),
                               name="__saw_rt_tcp_read")
        tcp_write = ir.Function(self.module, ir.FunctionType(i64, [i64, i8ptr, i64]),
                                name="__saw_rt_tcp_write")
        # design 89-c: the cooperative op-count budget seam. `saw_op_budget_tick()`
        # decrements the process-global work budget and returns 1 (with a reset to
        # the default) when it is exhausted — the caller then force-yields — else 0.
        # `saw_op_budget_reset()` restores the default (called on a genuine park).
        budtick = ir.Function(self.module, ir.FunctionType(i64, []),
                              name="__saw_rt_op_budget_tick")
        budreset = ir.Function(self.module, ir.FunctionType(void, []),
                               name="__saw_rt_op_budget_reset")
        # design 103 (A6): the blocking-extern offload shims. `saw_offload_start(fn,
        # arg)` spawns a thread-per-call that runs the extern and signals a self-pipe;
        # `saw_offload_done`/`saw_offload_pipe_fd`/`saw_offload_take` poll / expose the
        # readable fd / join+collect+free. `saw_blocking_sleep(ms)` is the reference
        # blocking primitive (a real thread-blocking sleep returning its argument) the
        # offload path and its tests exercise via a `blocking func` extern declaration.
        offload_start = ir.Function(self.module, ir.FunctionType(i64, [i64, i64]),
                                    name="__saw_rt_offload_start")
        offload_done = ir.Function(self.module, ir.FunctionType(i64, [i64]),
                                   name="__saw_rt_offload_done")
        offload_fd = ir.Function(self.module, ir.FunctionType(i64, [i64]),
                                 name="__saw_rt_offload_pipe_fd")
        offload_take = ir.Function(self.module, ir.FunctionType(i64, [i64]),
                                   name="__saw_rt_offload_take")
        blocking_sleep = ir.Function(self.module, ir.FunctionType(i64, [i64]),
                                     name="__saw_rt_blocking_sleep")
        io_fns = (create, reg, poll, wake, destroy, setnb, setfam, last_err,
                  tcp_listen, tcp_local_port, tcp_accept, tcp_connect_start,
                  tcp_connect_check, tcp_read, tcp_write, budtick, budreset,
                  offload_start, offload_done, offload_fd, offload_take,
                  blocking_sleep)
        for fn in io_fns:
            self.functions[fn.name] = fn
        # design 113b/117: every io seam body now lives in Saw + shim.c under
        # `sawc/rt/` (host_*/reactor.saw, host_*/net_os.saw, common/op_budget.saw,
        # common/offload.saw; set_nonblocking in shim.c — DF-113c). The compiler
        # only DECLARES them (external) and links the runtime; the reactor's last
        # synthesized bodies (the DF-113d per-call stack-buffer blocker) are GONE —
        # the instance now owns a per-call heap poll buffer, which Saw can express.
        # In `--runtime-build` a module's `@export` of a seam collapses into these
        # declarations (design-58 unify).
        for fn in io_fns:
            fn.linkage = "external"

        # design 117: the process-global reactor INSTANCE is executor POLICY, not
        # runtime state. Synthesize `__saw_reactor()` — a lazy, race-safe getter
        # holding the singleton in the slot the reactor fd used to occupy. It
        # `reactor_create()`s on first use, publishes it via cmpxchg, and a loser
        # `reactor_destroy()`s its spare. Every reactor seam CALL site (the io_wait
        # lowering, the entry executor, the ambient scheduler) is handed this
        # instance by codegen, so the Saw seam callers stay instance-agnostic. A
        # `--runtime-build` module never calls the seams by their ABI names, so it
        # needs no getter.
        if not self.runtime_build:
            self._synthesize_reactor_instance_getter(create, destroy)

    def _synthesize_reactor_instance_getter(self, create, destroy):
        """design 117: the process-global reactor instance getter `__saw_reactor()`.

        The reactor ABI is instance-based (register/poll/wake/destroy take an
        opaque instance from `reactor_create`); the compiler keeps the ONE
        process-global instance as executor policy in an internal global, created
        lazily and race-safely — exactly the CAS the pre-117 synthesized reactor
        used to publish its kqueue/epoll fd, now publishing the whole instance.
        Codegen injects the result at every reactor seam call site.
        """
        i64 = ir.IntType(64)
        inst_g = ir.GlobalVariable(self.module, i64, name="__saw_reactor_instance")
        inst_g.linkage = "internal"
        inst_g.initializer = ir.Constant(i64, 0)

        getter = ir.Function(self.module, ir.FunctionType(i64, []),
                             name="__saw_reactor")
        getter.linkage = "internal"
        self.functions["__saw_reactor"] = getter
        entry = getter.append_basic_block("entry")
        have_bb = getter.append_basic_block("have")
        make_bb = getter.append_basic_block("make")
        won_bb = getter.append_basic_block("won")
        lost_bb = getter.append_basic_block("lost")
        b = ir.IRBuilder(entry)
        cur = b.load(inst_g, name="cur")
        cur.ordering = "monotonic"; cur.align = 8
        b.cbranch(b.icmp_signed("!=", cur, ir.Constant(i64, 0)), have_bb, make_bb)
        b = ir.IRBuilder(have_bb)
        b.ret(cur)
        b = ir.IRBuilder(make_bb)
        newp = b.call(create, [], name="new_reactor")
        # cmpxchg __saw_reactor_instance : 0 -> newp (publish); on failure a peer won.
        cx = b.cmpxchg(inst_g, ir.Constant(i64, 0), newp, "seq_cst", "monotonic")
        old = b.extract_value(cx, 0, name="cx_old")
        ok = b.extract_value(cx, 1, name="cx_ok")
        b.cbranch(ok, won_bb, lost_bb)
        b = ir.IRBuilder(won_bb)
        b.ret(newp)
        b = ir.IRBuilder(lost_bb)
        b.call(destroy, [newp])          # discard our spare; use the winner's
        b.ret(old)

    def _create_string_literal_global(self, value: str) -> ir.GlobalVariable:
        """Create (or reuse) an immortal Saw String literal block.

        Layout: { i64 refcount = -1, i64 len, [len+1 x i8] bytes (NUL-terminated) }.
        Returned global's `bytes` field address is the String value.
        """
        if value in self.string_literal_globals:
            return self.string_literal_globals[value]

        encoded = value.encode('utf-8')
        n = len(encoded)
        arr_type = ir.ArrayType(ir.IntType(8), n + 1)
        # Design 47: header words are platform-width (isize), matching the String
        # runtime layout. On hosted this is the pre-47 { i64, i64, bytes } block.
        word = self.int_type
        hdr_type = ir.LiteralStructType([word, word, arr_type])

        name = f".sawstr.{self.string_counter}"
        self.string_counter += 1
        g = ir.GlobalVariable(self.module, hdr_type, name=name)
        g.linkage = 'private'
        g.global_constant = True
        g.initializer = ir.Constant(hdr_type, [
            ir.Constant(word, -1),   # immortal sentinel
            ir.Constant(word, n),
            ir.Constant(arr_type, bytearray(encoded + b'\0')),
        ])
        self.string_literal_globals[value] = g
        return g

    def _libc_func(self, name, return_type, arg_types, var_arg=False):
        """Get (or lazily declare) a libc function by name.

        Reuses an existing declaration if one is already in the function table
        (e.g. an `extern func malloc(...)` from a std module) so we never emit a
        duplicate symbol; otherwise declares it once and caches it.
        """
        if name in self.functions:
            return self.functions[name]
        fn_type = ir.FunctionType(return_type, arg_types, var_arg=var_arg)
        fn = ir.Function(self.module, fn_type, name=name)
        self.functions[name] = fn
        return fn

    def generate(self, program: Program) -> str:
        # Type aliases are already in namespace from typechecker

        # design 69: emit debug-info module flags + compile unit before any
        # function subprogram references them.
        self._di_setup_module()

        # Register built-in generic enums (like Result<T, E>)
        self._register_builtin_enums()

        # String is a compiler-known refcounted ImplicitCopy + Deinit type
        # (retain = copy, release = deinit). Register conformances so cleanup
        # tracking and transfer-site copies fire; emit the runtime helpers and
        # String.copy()/String.deinit() before extern blocks so the stdlib's
        # `extern` declarations of __saw_string_* resolve to these definitions.
        self.namespace.register_conformance("String", "ImplicitCopy")
        self.namespace.register_conformance("String", "Deinit")
        # Runtime seams must exist before the String runtime (which allocates via
        # saw_alloc) and before extern blocks (whose `extern func saw_alloc(...)`
        # declarations resolve to these definitions).
        self._declare_seams()
        self._declare_string_runtime()
        self._declare_argv_runtime()
        self._declare_print_runtime()
        self._declare_atomic_runtime()
        self._declare_pthread_runtime()
        self._declare_io_runtime()

        # Store generic and specialized extensions FIRST
        # This must happen before struct registration since structs with generic
        # field types (e.g., Vector<Foo>) trigger monomorphization which needs
        # access to generic extensions.
        # Design 37: a specialized extension written against the default-omitted
        # form (`extension Vector<String>`) must key by the FULLY-APPLIED type
        # args (`("String", "GlobalAllocator")`) so it matches a lookup on the resolved
        # `Vector<String, Global>`. Pad the concrete spec key with the struct's
        # declared trailing defaults. The struct ASTs carry the defaults; build a
        # lookup now (generic_structs is populated later, after this loop).
        struct_type_params_by_name = {s.name: s.type_params for s in program.structs}
        for extension in program.extensions:
            if extension.type_params:
                spec_key = self._get_extension_specialization(extension)
                if spec_key:
                    spec_key = self._pad_spec_key_with_defaults(
                        extension.struct_name, spec_key, struct_type_params_by_name)
                    # Specialized extension (e.g., extension Vector<String>)
                    full_key = (extension.struct_name, spec_key)
                    if full_key not in self.specialized_extensions:
                        self.specialized_extensions[full_key] = []
                    self.specialized_extensions[full_key].append(extension)
                else:
                    # Generic extension (e.g., extension Vector<T>)
                    if extension.struct_name not in self.generic_extensions:
                        self.generic_extensions[extension.struct_name] = []
                    self.generic_extensions[extension.struct_name].append(extension)
            else:
                # Non-generic-type extension. Design 40 item 9 (C6): any generic
                # METHOD it declares still needs per-method-arg monomorphization
                # (its type params are unbound), so index it for the call-site
                # specializer; the eager declare/generate passes skip it.
                for m in extension.methods:
                    if getattr(m, 'type_params', None) and not m.is_init:
                        self.plain_generic_methods.setdefault(
                            extension.struct_name, {})[m.name] = m

        # Register types in dependency order (structs and enums can reference each other)
        self._register_types_in_order(program.structs, program.enums)

        # Interfaces, type conformances, and type assignments are in namespace from typechecker

        # Declare extern functions (FFI)
        for extern_block in program.extern_blocks:
            for extern_func in extern_block.functions:
                self._declare_extern_function(extern_func)

        # Declare all functions (skip generic functions)
        for func in program.functions:
            if func.type_params:
                # Store generic function for later instantiation. Design 105: a
                # generic overload in a 2+ generic set carries a distinct `$OL$`
                # base symbol (registration) so its template is stored/looked up
                # under that base, not the collision-prone plain name.
                self.generic_functions[
                    getattr(func, 'mangled_symbol', None) or func.name] = func
            else:
                # Overloading (design 55): a member of a 2+ overload set is
                # emitted under its type-signature-suffixed symbol (stamped on
                # the AST node by the typechecker); others keep the plain name.
                self._declare_function(func, name_override=getattr(func, 'mangled_symbol', None))

        # Declare non-generic extension methods
        for extension in program.extensions:
            if not extension.type_params:
                self._declare_extension_methods(extension)

        # Emit module-level static globals (design 41). Done after types/functions
        # are declared so const initializers can reference them; before function
        # bodies so reads resolve.
        for static in getattr(program, 'statics', []):
            self._emit_static_global(static)

        # Design 53: evaluate top-level `static_assert`s now that statics/types
        # exist (so sizeof/alignof and const-static references resolve). A false
        # assertion is a clean compile error; a true one emits nothing.
        for sa in getattr(program, 'static_asserts', []):
            self._eval_static_assert(sa)

        # Fifth pass: generate function bodies (skip generic functions)
        for func in program.functions:
            if not func.type_params:
                self._generate_function(func, name_override=getattr(func, 'mangled_symbol', None))

        # Generate extension method bodies
        for extension in program.extensions:
            self._generate_extension_methods(extension)

        # Generate pending monomorphized method bodies
        # These were queued during monomorphization to ensure all signatures exist first
        self._generate_pending_method_bodies()

        # design 51: fill any `any Trait` vtables requested during body codegen
        # (destructor + method thunks) now that every impl function is declared.
        self._emit_pending_vtables()

        # design 58: anchor `@export`ed symbols against DCE.
        self._emit_llvm_used()

        # design 112: in the freestanding profile, place every function in its
        # own `.text.<name>` section so a kernel linker (`ld.lld --gc-sections`)
        # can garbage-collect the unreachable stdlib methods. Codegen emits EVERY
        # loaded extension method regardless of reachability, and freestanding
        # still loads channel/mutex/task/float-print methods — which reference
        # pthread/snprintf/float libcalls. Without per-function sections they all
        # fuse into one `.text` that a single reachable call pins whole, so the
        # link pulls in symbols a bare-metal target can't satisfy. Per-function
        # sections + `--gc-sections` keeps only the transitively-reachable set
        # (entry + `@llvm.used`). Guarded by `freestanding`: hosted builds are
        # byte-identical to before.
        if self.freestanding:
            self._apply_freestanding_sections()
        elif self.runtime_build:
            # design 113b: a runtime-build object keeps ONLY its `@export`ed
            # seams external; every other definition (String/atomic/print/argv
            # helpers pulled in with the prelude, the runtime's own private
            # globals) is internalized so it never collides with the user
            # program's copies at link time, and globaldce drops the unused. No
            # per-symbol `.text.<name>` sectioning: this object is linked by
            # clang on the HOST (mach-O rejects that ELF section spelling), and
            # -O1 globaldce already strips the unreferenced internal defs.
            self._apply_freestanding_sections(place_sections=False)

        return str(self.module)

    def _apply_freestanding_sections(self, place_sections: bool = True):
        """Prepare the freestanding module for dead-code-free linking (design 112).

        `place_sections=False` (design 113b runtime-build): internalize only, with
        NO per-symbol section assignment — the object is host-linked by clang and
        the mach-O host rejects the ELF `.text.<name>` spelling.

        Codegen emits EVERY loaded stdlib method (and its closure/vtable
        descriptor globals + backend constant pools) regardless of reachability,
        and the freestanding profile still loads channel/mutex/task/float-print
        methods — which reference pthread/snprintf/float/atomic symbols a
        bare-metal target cannot satisfy. Two composing mechanisms strip them so a
        kernel links only what it uses:

        1. INTERNALIZE every definition that is not an `@export` keep-root (nor the
           C `main`). With external linkage the O1 `globaldce` must treat each as a
           root; internal linkage lets it delete everything unreachable from the
           exported entry (`kmain`) + `@llvm.used`. This is the primary mechanism
           and removes the dead methods' fused backend constant pools too — the
           part per-section splitting alone cannot reach (llvmlite exposes no
           backend function/data-sections knob).
        2. PER-SYMBOL SECTIONS (`.text.<n>` / `.rodata.<n>` / `.data.<n>`) so a
           `ld.lld --gc-sections` link trims any residue (and covers `-O0`, where
           globaldce does not run). Only definitions without an explicit
           `@section` are placed; declarations and `llvm.*` anchors are left alone.

        Guarded by `freestanding`, so hosted builds are byte-identical.
        """
        # Keep-roots: the exported functions/statics (already anchored in
        # `@llvm.used`) plus the C `main` if present. Everything else internalizes.
        keep = {g.name for g in self._exported_llvm_globals}
        keep.add("main")

        for fn in self.module.functions:
            if not fn.blocks:
                continue  # declaration / intrinsic — nothing to place
            if fn.name.startswith('llvm.'):
                continue
            if fn.name not in keep:
                fn.linkage = "internal"
            if place_sections and not getattr(fn, 'section', None):
                fn.section = f".text.{fn.name}"

        for gv in self.module.global_values:
            if not isinstance(gv, ir.GlobalVariable):
                continue  # functions handled above
            if gv.initializer is None:
                continue  # external declaration — no storage here
            if gv.name.startswith('llvm.'):
                continue  # llvm.used / metadata anchors stay put
            if gv.name not in keep:
                gv.linkage = "internal"
            if place_sections and not getattr(gv, 'section', None):
                # Constants (incl. relro tables of function pointers, resolved at
                # link time in a static kernel) → `.rodata.<name>`; mutable data →
                # `.data.<name>`. The kernel linker script catches `.rodata.*` and
                # `.data.*`; `--gc-sections` drops the unreferenced ones.
                prefix = ".rodata" if gv.global_constant else ".data"
                gv.section = f"{prefix}.{gv.name}"

    # ---- design 53: static_assert compile-time evaluation ----

    def _eval_static_assert(self, sa):
        """Evaluate one `static_assert(cond, "msg")`. A false result raises a
        clean compile error carrying the message; a true result emits nothing."""
        value = self._const_eval(sa.condition, sa)
        if not bool(value):
            raise StaticAssertError(
                f"static assertion failed: {sa.message}", sa.line, sa.column)

    def _const_eval(self, expr, sa):
        """Compile-time-evaluate a constant expression to a Python int/bool for
        static_assert (design 53). Supports integer/bool literals, unary `-`/
        `not`, arithmetic/comparison/logical operators, `sizeof<T>()`/
        `alignof<T>()`, and the `Int.max`/`.min` integer limits. Anything else is
        rejected as non-constant with a clean error."""
        if isinstance(expr, BoolLiteral):
            return bool(expr.value)
        if isinstance(expr, IntLiteral):
            return int(expr.value)
        if isinstance(expr, UnaryOp):
            if expr.op == '-':
                return -self._const_eval(expr.operand, sa)
            if expr.op == 'not':
                return not self._const_eval(expr.operand, sa)
            self._reject_const(expr, sa, f"unary operator `{expr.op}`")
        if isinstance(expr, BinaryOp):
            left = self._const_eval(expr.left, sa)
            right = self._const_eval(expr.right, sa)
            op = expr.op
            if op == '+': return left + right
            if op == '-': return left - right
            if op == '*': return left * right
            if op == '/':
                if right == 0:
                    self._reject_const(expr, sa, "division by zero")
                q = abs(left) // abs(right)
                return -q if (left < 0) ^ (right < 0) else q
            if op == '%':
                if right == 0:
                    self._reject_const(expr, sa, "modulo by zero")
                r = abs(left) % abs(right)
                return -r if left < 0 else r
            if op == '==': return left == right
            if op == '!=': return left != right
            if op == '<': return left < right
            if op == '>': return left > right
            if op == '<=': return left <= right
            if op == '>=': return left >= right
            if op == '&&': return bool(left) and bool(right)
            if op == '||': return bool(left) or bool(right)
            self._reject_const(expr, sa, f"operator `{op}`")
        if isinstance(expr, FunctionCall):
            if expr.name == 'sizeof':
                return self._const_type_metric(expr, sa, 'size')
            if expr.name == 'alignof':
                return self._const_type_metric(expr, sa, 'align')
            self._reject_const(expr, sa, f"call to `{expr.name}`")
        if isinstance(expr, MemberAccess):
            limit = getattr(expr, 'int_limit', None)
            if limit is not None:
                return self._const_int_limit(limit)
            self._reject_const(expr, sa, "this member access")
        self._reject_const(expr, sa, type(expr).__name__)

    # ---------------------------------------------------------------------
    # ABI layout queries (design 115 re-entrancy).
    #
    # `ir.Type.get_abi_size`/`get_abi_alignment` compute layout by rendering the
    # type into a THROWAWAY module and parsing it. Called with no `context=`,
    # llvmlite builds that module in its process-GLOBAL context, whose
    # identified-type registry does NOT contain the struct bodies this compile
    # registered in its own fresh `ir.Context()` (see `__init__`) — so an
    # identified struct type renders as an undefined-type reference and the parse
    # fails ("use of undefined type named ..."). Passing this compile's OWN
    # module context makes the throwaway module self-contained. Route every ABI
    # query through these helpers so the per-compile context stays correct.
    def _abi_size(self, llvm_type) -> int:
        return llvm_type.get_abi_size(self.target_data, context=self.module.context)

    def _abi_align(self, llvm_type) -> int:
        return llvm_type.get_abi_alignment(self.target_data,
                                           context=self.module.context)

    def _const_type_metric(self, expr, sa, which):
        if not expr.type_args or len(expr.type_args) != 1:
            self._reject_const(expr, sa, f"`{expr.name}` needs one type argument")
        saw_type = expr.type_args[0]
        if (saw_type.kind == TypeKind.STRUCT
                and saw_type.struct_name in self.type_param_context):
            saw_type = self.type_param_context[saw_type.struct_name]
        llvm_type = self._get_llvm_type(saw_type)
        if which == 'size':
            return self._abi_size(llvm_type)
        return self._abi_align(llvm_type)

    def _const_int_limit(self, limit):
        type_name, which = limit
        width, signed = self._INT_LIMIT_SPECS[type_name]
        if width is None:
            width = self.int_width
        if which == "max":
            return (1 << (width - 1)) - 1 if signed else (1 << width) - 1
        return -(1 << (width - 1)) if signed else 0

    def _reject_const(self, expr, sa, what):
        raise StaticAssertError(
            f"static_assert condition is not a compile-time constant: "
            f"{what} is not allowed here", sa.line, sa.column)

    # _resolve_type_alias is now in codegen_types.py (TypesMixin)

    def _register_types_in_order(self, structs, enums):
        """Register structs and enums in dependency order using topological sort."""
        from ast_nodes import TypeKind

        # Build maps for quick lookup
        struct_map = {s.name: s for s in structs}
        enum_map = {e.name: e for e in enums}
        all_types = set(struct_map.keys()) | set(enum_map.keys())

        # Helper to get type dependencies from a SawType
        def get_deps(saw_type):
            deps = set()
            if saw_type.kind == TypeKind.STRUCT and saw_type.struct_name in all_types:
                deps.add(saw_type.struct_name)
            elif saw_type.kind == TypeKind.ENUM and saw_type.enum_name in all_types:
                deps.add(saw_type.enum_name)
            # Check type args for generics like Vector<MyStruct>
            if saw_type.type_args:
                for arg in saw_type.type_args:
                    deps.update(get_deps(arg))
            # Check inner_type for optionals, pointers, references, etc.
            if saw_type.inner_type:
                deps.update(get_deps(saw_type.inner_type))
            # Check tuple element types.
            if saw_type.element_types:
                for elem in saw_type.element_types:
                    deps.update(get_deps(elem))
            # Check the element type of a fixed array `[T; N]`: a struct field of
            # array type depends on its element type's layout being registered
            # first (design 33). Missing this let the topological sort place a
            # container struct before its array element type, so building the
            # container's LLVM type failed with "Undefined struct" nondeterministically
            # (the order depended on set iteration / hash seed).
            if saw_type.kind == TypeKind.ARRAY and saw_type.array_element_type:
                deps.update(get_deps(saw_type.array_element_type))
            return deps

        # Build dependency graph
        deps = {name: set() for name in all_types}

        for struct in structs:
            if struct.type_params:
                continue  # Skip generic structs
            for field in struct.fields:
                deps[struct.name].update(get_deps(field.type))

        for enum in enums:
            if enum.type_params:
                continue  # Skip generic enums
            for variant in enum.variants:
                for _, param_type in variant.associated_types:
                    deps[enum.name].update(get_deps(param_type))

        # Topological sort using Kahn's algorithm
        in_degree = {name: 0 for name in all_types}
        for name, type_deps in deps.items():
            for dep in type_deps:
                if dep in in_degree:
                    in_degree[name] += 1

        # Start with types that have no dependencies
        queue = [name for name, degree in in_degree.items() if degree == 0]
        sorted_types = []

        while queue:
            name = queue.pop(0)
            sorted_types.append(name)

            # Find types that depend on this one and reduce their in-degree
            for other_name, other_deps in deps.items():
                if name in other_deps:
                    in_degree[other_name] -= 1
                    if in_degree[other_name] == 0:
                        queue.append(other_name)

        # Add any remaining types (may have cycles - just add them)
        for name in all_types:
            if name not in sorted_types:
                sorted_types.append(name)

        # Register in sorted order
        for name in sorted_types:
            if name in struct_map:
                self._register_struct(struct_map[name])
            elif name in enum_map:
                self._register_enum(enum_map[name])

    def _register_struct(self, struct: Struct):
        """Register a struct type with LLVM."""
        # Skip generic structs - they'll be monomorphized when used
        if struct.type_params:
            self.generic_structs[struct.name] = struct
            return

        # Get LLVM types for each field
        field_types = [self._get_llvm_type(field.type) for field in struct.fields]

        # Create identified struct type (unique identity even if same field types)
        llvm_struct_type = self.module.context.get_identified_type(struct.name)
        llvm_struct_type.set_body(*field_types)

        # Store the type and field order for later use
        field_order = [field.name for field in struct.fields]
        self.struct_types[struct.name] = (llvm_struct_type, field_order)
        # Struct field types are in namespace

    def _register_builtin_enums(self):
        """Register built-in generic enums like Result<T, E>.

        These are defined as builtins in the typechecker but need to be
        registered in codegen for monomorphization.
        """
        # Create a synthetic Enum AST node for Result<T, E>
        result_enum = Enum(
            name="Result",
            variants=[
                EnumVariant(
                    name="Ok",
                    associated_types=[("value", SawType(TypeKind.TYPE_PARAM, type_param_name="T"))]
                ),
                EnumVariant(
                    name="Err",
                    associated_types=[("error", SawType(TypeKind.TYPE_PARAM, type_param_name="E"))]
                )
            ],
            type_params=[
                TypeParameter(name="T", line=0, column=0),
                TypeParameter(name="E", line=0, column=0)
            ],
            line=0, column=0
        )
        self.generic_enums["Result"] = result_enum

    def _register_enum(self, enum: Enum):
        """Register an enum type with LLVM.
        Enums are represented as tagged unions: { i32 tag, [N x i8] payload }
        or just i32 if all variants have no associated values."""
        # Skip generic enums - they'll be monomorphized when used
        if enum.type_params:
            self.generic_enums[enum.name] = enum
            return

        self._register_concrete_enum(enum.name, enum.variants)

    def _register_concrete_enum(self, name: str, variants: List[EnumVariant]):
        """Register a concrete (non-generic or monomorphized) enum type with LLVM."""
        # Assign tag values to variants (0, 1, 2, ...)
        variant_tags = {}
        variant_info = {}
        max_payload_size = 0

        for i, variant in enumerate(variants):
            variant_tags[variant.name] = i
            variant_info[variant.name] = variant.associated_types

            # Calculate payload size for this variant
            if variant.associated_types:
                # A Void-typed payload field carries no data (design 92:
                # `Result<Void, E>` — the Ok arm is dataless). Drop it so the
                # variant struct never contains an illegal `{void}` member; an
                # all-Void variant contributes a zero-size (payload-free) arm.
                variant_types = [self._get_llvm_type(typ) for _, typ in variant.associated_types
                                 if not isinstance(self._get_llvm_type(typ), ir.VoidType)]
                # Create a struct to hold the associated values
                if variant_types:
                    variant_struct = ir.LiteralStructType(variant_types)
                    # Size the payload byte array by the variant struct's TRUE ABI
                    # size (via LLVM's DataLayout), NOT a naive field-size sum. The
                    # sum ignores alignment padding, so any payload with internal
                    # padding — a pointer/optional after a smaller field, e.g.
                    # `Arc<T>` (an optional pointer `{i1, ptr}` = 16 bytes, sum 9)
                    # or an `Int8` before a wide field — undersizes `[N x i8]` and
                    # both TRUNCATES the aggregate on construction and reads OOB on
                    # extraction (design 65, L17 symptom 2).
                    size = self._abi_size(variant_struct)
                    max_payload_size = max(max_payload_size, size)

        # Create LLVM type for enum
        if max_payload_size > 0:
            # Enum with associated values: { i32 tag, [N x i8] payload }
            llvm_enum_type = ir.LiteralStructType([
                ir.IntType(32),  # tag
                ir.ArrayType(ir.IntType(8), max_payload_size)  # payload
            ])
        else:
            # Simple enum (no associated values): just i32 tag
            llvm_enum_type = ir.IntType(32)

        # Store enum info
        self.enum_types[name] = (llvm_enum_type, variant_tags, variant_info)

    # _estimate_type_size is now in codegen_types.py (TypesMixin)

    def _mark_noalias_params(self, llvm_func, saw_types, arg_offset=0):
        """Mark `&var` (mutable-reference) parameters `noalias`.

        The Law of Exclusivity (brief 10) statically guarantees a `&var` binding
        is the only live access path to its referent for the whole call, so
        LLVM's `noalias` contract -- this pointer does not alias any other
        pointer the function accesses -- holds by construction. Declaring it lets
        the optimizer keep loads/stores through the reference in registers rather
        than reloading defensively. Immutable `&` params are intentionally NOT
        marked: multiple `&` readers of the same value may legitimately coexist.

        `saw_types` is the parameter SawTypes in LLVM-arg order; `arg_offset`
        skips leading synthetic args (e.g. a closure's env pointer at arg 0).
        """
        for i, st in enumerate(saw_types):
            if (st is not None
                    and st.kind == TypeKind.REFERENCE
                    and st.reference_mutable
                    # `&var any Trait` (design 51) is a fat STRUCT, not a pointer;
                    # `noalias` is a pointer-only attribute, so skip it there.
                    and not (st.inner_type is not None
                             and st.inner_type.kind == TypeKind.EXISTENTIAL)):
                llvm_func.args[arg_offset + i].add_attribute('noalias')

    def _declare_function(self, func: Function, name_override: str = None):
        """Declare a function. If name_override is provided, use it instead of func.name.

        design 58: an `@export`ed function keeps `func_name` as the lookup key
        Saw-side callers use, but its LLVM symbol is the requested C name
        (`@export` / `@export("sym")`) — unmangled, external linkage, kept alive
        against DCE. `@section("...")` places it in a named object-file section.
        """
        from ast_nodes import is_exported, export_symbol, section_name
        func_name = name_override if name_override else func.name  # self.functions key
        exported = is_exported(func)
        c_symbol = export_symbol(func) if exported else None
        llvm_name = c_symbol if c_symbol else func_name

        param_types = [self._get_llvm_type(p.type) for p in func.parameters]
        # The C entry `main` receives (argc, argv) from the runtime. A Saw `main`
        # is always declared no-arg, so give the emitted `main` the C entry
        # signature and stash the two arguments into the argv globals in its
        # prologue (design 81 CI rider) — the cross-platform argc/argv source.
        if func_name == "main" and not func.parameters:
            param_types = [ir.IntType(32), ir.IntType(8).as_pointer().as_pointer()]
        is_never = func.return_type.kind == TypeKind.NEVER
        if is_never:
            # A `-> Never` function diverges: lower to `void` + `noreturn` (the
            # `_start`/noreturn C shape). The body terminates with `unreachable`.
            return_type = ir.VoidType()
        else:
            return_type = self._get_llvm_type(func.return_type)

        # Main function should return int for proper exit code
        if func_name == "main" and func.return_type.kind == TypeKind.VOID:
            return_type = ir.IntType(32)

        func_type = ir.FunctionType(return_type, param_types)

        # Unify with a pre-existing bodyless declaration of the same LLVM symbol
        # (e.g. an `extern "C"` import of an `@export`ed symbol in the same unit)
        # so the definition and declaration collapse into ONE function instead of
        # colliding. Only for exports, where symbol sharing is intentional.
        llvm_func = None
        if exported:
            try:
                existing = self.module.get_global(llvm_name)
            except KeyError:
                existing = None
            if isinstance(existing, ir.Function) and len(existing.blocks) == 0:
                llvm_func = existing
        if llvm_func is None:
            llvm_func = ir.Function(self.module, func_type, name=llvm_name)

        if is_never:
            llvm_func.attributes.add("noreturn")
        if exported:
            # Default function linkage ('') already emits a `define` with external
            # visibility (the symbol is in the object's symbol table for the C
            # linker) and the C calling convention. Anchor it against DCE with
            # `@llvm.used`. Setting linkage="external" on a DEFINITION is invalid.
            if llvm_func not in self._exported_llvm_globals:
                self._exported_llvm_globals.append(llvm_func)
        sec = section_name(func)
        if sec:
            llvm_func.section = sec

        self.functions[func_name] = llvm_func
        self._mark_noalias_params(llvm_func, [p.type for p in func.parameters])
        # Function return types are now in namespace

        # Track default parameter values (design 53) so an omitted trailing
        # argument is filled at the call site.
        defaults = [p.default_value for p in func.parameters]
        if any(d is not None for d in defaults):
            self.func_defaults[func_name] = defaults

    def _declare_extern_function(self, extern_func: ExternFunction):
        """Declare an external C function (no body, just LLVM declare)."""
        # Record the optional-return wrapping BEFORE any early-out: a
        # compiler-emitted runtime helper (e.g. __saw_string_alloc) may already
        # be defined under this name, but call sites still need the NULL->None
        # wrapping registered from the extern signature.
        saw_return_type = extern_func.return_type
        if saw_return_type.kind == TypeKind.OPTIONAL and saw_return_type.inner_type:
            self.extern_optional_returns[extern_func.name] = saw_return_type.inner_type

        # Skip if already declared (std library and user code both declaring, or
        # a compiler-provided definition already emitted).
        if extern_func.name in self.functions:
            return

        param_types = [self._get_llvm_type(p.type) for p in extern_func.parameters]

        # For extern functions, unwrap optionals from return type for C ABI
        # C functions return raw pointers which can be NULL
        if saw_return_type.kind == TypeKind.OPTIONAL and saw_return_type.inner_type:
            return_type = self._get_llvm_type(saw_return_type.inner_type)
        else:
            return_type = self._get_llvm_type(saw_return_type)

        func_type = ir.FunctionType(return_type, param_types, var_arg=extern_func.is_variadic)
        llvm_func = ir.Function(self.module, func_type, name=extern_func.name)
        # Set external linkage (default for declarations)
        llvm_func.linkage = 'external'
        self.functions[extern_func.name] = llvm_func

    # Generic methods moved to codegen_generics.py (GenericsMixin)

    def _declare_extension_methods(self, extension: Extension):
        """Declare all methods in an extension."""
        # Generic extensions are already stored and will be monomorphized when used
        if extension.type_params:
            return

        # Set Self type context for this extension
        old_self_context = self.self_type_context
        self.self_type_context = extension.struct_name

        for method in extension.methods:
            # Design 40 item 9 (C6): a generic method's signature can't be
            # declared until its type params are bound at the call site; skip it
            # here (it is indexed in plain_generic_methods and specialized then).
            if getattr(method, 'type_params', None) and not method.is_init:
                continue
            # Create mangled name. Overloading (design 55): a member of a 2+
            # method overload set carries a type-signature symbol stamped on the
            # AST node; use it so the definition matches the resolved call site.
            overload_symbol = getattr(method, 'mangled_symbol', None)
            if overload_symbol is not None:
                mangled_name = overload_symbol
            elif method.is_init:
                # Include parameter names for init methods to allow overloading
                param_names = [p.name for p in method.parameters]
                mangled_name = self._mangle_method_name(extension.struct_name, method.name, param_names)
            else:
                mangled_name = self._mangle_method_name(extension.struct_name, method.name)

            # Build parameter types
            if method.is_init:
                # Init methods take parameters (no self) and return the struct
                # Primitive type extensions (String) don't support init methods
                if extension.struct_name == "String":
                    raise ValueError("Cannot define init methods on String")
                param_types = [self._get_llvm_type(p.type) for p in method.parameters]
                # Return type is the struct being initialized
                struct_type, _ = self.struct_types[extension.struct_name]
                return_type = struct_type
            elif method.is_static:
                # Static methods have no self parameter
                param_types = [self._get_llvm_type(p.type) for p in method.parameters]
                return_type = self._get_llvm_type(method.return_type)
            else:
                # Regular instance methods include self as first parameter
                # Determine the Self type for this extension
                self_llvm_type = self._primitive_self_llvm_type(extension.struct_name)
                if self_llvm_type is None:
                    self_llvm_type = self.struct_types[extension.struct_name][0]

                param_types = []
                for i, p in enumerate(method.parameters):
                    # Handle 'self' parameter specially - its type is VOID placeholder
                    if p.name == "self":
                        llvm_type = self_llvm_type
                    else:
                        llvm_type = self._get_llvm_type(p.type)
                    # If first param is self and it's mutable, make it a pointer
                    if i == 0 and p.name == "self" and method.self_mutable:
                        llvm_type = llvm_type.as_pointer()
                    param_types.append(llvm_type)
                return_type = self._get_llvm_type(method.return_type)

            # Create function type
            func_type = ir.FunctionType(return_type, param_types)
            llvm_func = ir.Function(self.module, func_type, name=mangled_name)

            # Mark &var params noalias. Explicit &var value params carry a
            # REFERENCE SawType; a `&var self` receiver is a distinct pointer arg
            # at index 0 (its parameter type is the VOID self-placeholder), so
            # mark it separately. Both are exclusivity-guaranteed non-aliasing.
            self._mark_noalias_params(llvm_func, [p.type for p in method.parameters])
            if (not method.is_init and not method.is_static
                    and getattr(method, 'self_mutable', False)):
                llvm_func.args[0].add_attribute('noalias')

            # Store in functions table
            self.functions[mangled_name] = llvm_func
            # Method return types and static method info are in namespace

            # Track default parameter values
            defaults = [p.default_value for p in method.parameters]
            if any(d is not None for d in defaults):
                self.method_defaults[mangled_name] = defaults

        # Restore Self type context
        self.self_type_context = old_self_context

    # Method/function generation moved to codegen_methods.py (MethodsMixin)
    # Statement generation moved to codegen_statements.py (StatementsMixin)

    def _generate_expression(self, expr: Expression, need_result: bool = True):
        """Generate code for an expression.

        Args:
            expr: The expression to generate code for
            need_result: If False, we don't need the expression's value (statement context).
                        This allows skipping result-capturing logic in if/if-let.
        """
        # Store the flag so nested calls can access it
        old_need_result = getattr(self, '_need_result', True)
        self._need_result = need_result

        method_name = f'visit_{expr.__class__.__name__}'
        visitor = getattr(self, method_name, None)
        if visitor is None:
            raise ValueError(f"Unknown expression type: {type(expr)}")
        result = visitor(expr)

        self._need_result = old_need_result
        return result

    # ===== Expression Visitor Methods =====

    def visit_IntLiteral(self, expr: IntLiteral):
        # Design 47: an integer literal is a platform `Int`, materialized at the
        # target's pointer width. A literal that does not fit the platform word
        # (signed low bound through unsigned high bound, so both Int.min's
        # magnitude and the full UInt range are admitted) is a compile error at
        # the literal — on a 32-bit target this loudly rejects a constant that
        # would otherwise silently truncate. Hosted targets are 64-bit, so every
        # literal the pre-47 compiler accepted still fits.
        # Design 53: a suffixed literal (`255u8`) is materialized at the suffix's
        # fixed width. Its value was range-checked at lex time; emit the bit
        # pattern masked to the width (a high-bit signed literal like `255i8`
        # reads back as -1, matching the two's-complement interpretation).
        suffix = getattr(expr, 'suffix', None)
        if suffix is not None:
            width = {'i8': 8, 'i16': 16, 'i32': 32, 'i64': 64,
                     'u8': 8, 'u16': 16, 'u32': 32, 'u64': 64}[suffix]
            return ir.Constant(ir.IntType(width), expr.value & ((1 << width) - 1))
        # Design 87: a bare literal that adopted a fixed-width type (the
        # typechecker stamped `resolved_type` via expected-type propagation, and
        # already range-checked it) is materialized at that width — so it stores,
        # compares, and overflow-checks at the slot's width with no downstream
        # reconcile. A platform-Int literal keeps the target word width below.
        _FIXED_INT_WIDTHS = {
            TypeKind.INT8: 8, TypeKind.INT16: 16, TypeKind.INT32: 32,
            TypeKind.INT64: 64, TypeKind.UINT8: 8, TypeKind.UINT16: 16,
            TypeKind.UINT32: 32, TypeKind.UINT64: 64,
        }
        resolved = getattr(expr, 'resolved_type', None)
        if resolved is not None and resolved.kind in _FIXED_INT_WIDTHS:
            fw = _FIXED_INT_WIDTHS[resolved.kind]
            return ir.Constant(ir.IntType(fw), expr.value & ((1 << fw) - 1))
        w = self.int_width
        if not (-(1 << (w - 1)) <= expr.value < (1 << w)):
            raise ValueError(
                f"integer literal {expr.value} does not fit in the {w}-bit "
                f"platform Int of target '{self.triple}'; use a fixed-width type "
                f"(e.g. Int64) for a value wider than the platform word")
        return ir.Constant(self.int_type, expr.value)

    def visit_FloatLiteral(self, expr: FloatLiteral):
        return ir.Constant(ir.DoubleType(), expr.value)

    def visit_BoolLiteral(self, expr: BoolLiteral):
        return ir.Constant(ir.IntType(1), 1 if expr.value else 0)

    def visit_StringLiteral(self, expr: StringLiteral):
        # Immortal refcounted String literal: pointer to the `bytes` field of a
        # static { i64 -1, i64 len, [N+1 x i8] } block. refcount == -1 makes
        # retain/release no-ops, so literals are never freed and cost no atomics.
        g = self._create_string_literal_global(expr.value)
        zero = ir.Constant(ir.IntType(32), 0)
        two = ir.Constant(ir.IntType(32), 2)  # index of the bytes array field
        return self.builder.gep(g, [zero, two, zero], inbounds=True)

    def visit_SourceLocationLiteral(self, expr):
        """A `#file`/`#line`/`#function` literal (design 98) — the typechecker
        froze it to a compile-time constant at its definition site, so this
        emits exactly a plain Int (platform-width) or String literal. Zero
        runtime cost."""
        if getattr(expr, 'resolved_kind', None) == 'int':
            return ir.Constant(self.int_type, expr.resolved_int)
        # 'string': an immortal refcounted String literal, exactly like
        # visit_StringLiteral.
        g = self._create_string_literal_global(expr.resolved_str or "")
        zero = ir.Constant(ir.IntType(32), 0)
        two = ir.Constant(ir.IntType(32), 2)
        return self.builder.gep(g, [zero, two, zero], inbounds=True)

    def visit_StringInterpolation(self, expr: StringInterpolation):
        """Generate code for string interpolation: "Hello {name}!"

        Strategy: measure the exact byte length, build a fresh refcounted String
        buffer of that size (refcount=1), then concatenate the literal parts and
        stringified expressions into it. The result is an owned Deinit value that
        participates in scope cleanup like any other String — no leak.
        """
        zero = ir.Constant(ir.IntType(32), 0)
        i8 = ir.IntType(8)
        i8ptr = i8.as_pointer()
        # Design 47: strlen returns size_t and __saw_string_alloc takes a
        # platform-width length, so the length math runs at the platform word.
        i64 = self.int_type

        # Convert every interpolated expression to a C string pointer once; the
        # same pointers are reused for both the length pass and the build pass.
        # Builtins keep the existing fast lowering (byte-identical). A non-builtin
        # Printable piece is rendered via its `to_string()` -> owned String (a
        # NUL-terminated i8*), spliced in like any String piece (design 56).
        piece_ptrs = []
        for sub_expr in expr.expressions:
            saw_type = self._expr_type(sub_expr)
            if saw_type is not None and self.type_param_context:
                saw_type = saw_type.substitute(self.type_param_context)
            if saw_type is not None:
                saw_type = self._resolve_type_alias(saw_type)
            if self._is_builtin_interp_type(saw_type):
                value = self._generate_expression(sub_expr)
                piece_ptrs.append(self._value_to_string(value, saw_type))
            else:
                mc = MethodCall(object=sub_expr, method_name="to_string",
                                arguments=[], line=expr.line, column=expr.column)
                mc.resolved_type = SawType(TypeKind.STRING)
                piece_ptrs.append(self._generate_expression(mc))

        strlen_fn = self._libc_func("strlen", i64, [i8ptr])

        # Total length: the literal parts are known at compile time; the
        # interpolated pieces are measured at runtime with strlen.
        literal_bytes = sum(len(p.encode('utf-8')) for p in expr.parts)
        total_len = ir.Constant(i64, literal_bytes)
        for ptr in piece_ptrs:
            piece_len = self.builder.call(strlen_fn, [ptr], name="piece_len")
            total_len = self.builder.add(total_len, piece_len, name="interp_len")

        # Allocate a refcounted String block (header + total_len + NUL,
        # refcount=1, len=total_len). The returned pointer addresses the bytes
        # region and is NUL-terminated, so strcpy/strcat below are safe and the
        # result is a valid owned String freed by its scope's release().
        buf = self.builder.call(self.functions["__saw_string_alloc"],
                                [total_len], name="interp_buf")

        # Build the string: strcpy the first literal part, then strcat each
        # piece and the following literal part in order. The buffer is exactly
        # sized, so these are safe.
        if expr.parts[0]:
            first = self._create_string_constant(expr.parts[0])
            first_ptr = self.builder.gep(first, [zero, zero], inbounds=True)
            self.builder.call(self.strcpy, [buf, first_ptr])
        else:
            # Empty first part - set null terminator so strcat has a valid start.
            self.builder.store(ir.Constant(i8, 0), buf)

        for i, ptr in enumerate(piece_ptrs):
            self.builder.call(self.strcat, [buf, ptr])
            if expr.parts[i + 1]:
                part = self._create_string_constant(expr.parts[i + 1])
                part_ptr = self.builder.gep(part, [zero, zero], inbounds=True)
                self.builder.call(self.strcat, [buf, part_ptr])

        return buf

    def _value_to_string(self, value, saw_type: SawType):
        """Convert an LLVM value to a string pointer using snprintf."""
        zero = ir.Constant(ir.IntType(32), 0)

        if saw_type is None:
            # Fallback for unknown types
            fallback = self._create_string_constant("<?>")
            return self.builder.gep(fallback, [zero, zero], inbounds=True)

        if saw_type.kind == TypeKind.STRING:
            return value  # Already a string

        # Allocate buffer for number-to-string conversion (64 bytes is enough)
        buf_size = 64
        buf = self._entry_alloca(ir.ArrayType(ir.IntType(8), buf_size), name="fmt_buf")
        buf_ptr = self.builder.gep(buf, [zero, zero], inbounds=True)
        size = ir.Constant(ir.IntType(64), buf_size)

        if saw_type.kind == TypeKind.BOOL:
            # Bool: use select for "true"/"false"
            true_str = self._create_string_constant("true")
            false_str = self._create_string_constant("false")
            true_ptr = self.builder.gep(true_str, [zero, zero], inbounds=True)
            false_ptr = self.builder.gep(false_str, [zero, zero], inbounds=True)
            return self.builder.select(value, true_ptr, false_ptr)

        elif saw_type.kind in {TypeKind.INT, TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64}:
            fmt = self._create_string_constant("%lld")
            fmt_ptr = self.builder.gep(fmt, [zero, zero], inbounds=True)
            # Extend to i64 if needed
            if value.type.width < 64:
                value = self.builder.sext(value, ir.IntType(64), name="sext_fmt")
            self.builder.call(self.snprintf, [buf_ptr, size, fmt_ptr, value])
            return buf_ptr

        elif saw_type.kind in {TypeKind.UINT, TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64}:
            fmt = self._create_string_constant("%llu")
            fmt_ptr = self.builder.gep(fmt, [zero, zero], inbounds=True)
            # Extend to i64 if needed
            if value.type.width < 64:
                value = self.builder.zext(value, ir.IntType(64), name="zext_fmt")
            self.builder.call(self.snprintf, [buf_ptr, size, fmt_ptr, value])
            return buf_ptr

        elif saw_type.kind == TypeKind.FLOAT:
            fmt = self._create_string_constant("%g")
            fmt_ptr = self.builder.gep(fmt, [zero, zero], inbounds=True)
            self.builder.call(self.snprintf, [buf_ptr, size, fmt_ptr, value])
            return buf_ptr

        else:
            # Fallback for unknown types
            fallback = self._create_string_constant("<?>")
            return self.builder.gep(fallback, [zero, zero], inbounds=True)

    _BUILTIN_INTERP_KINDS = frozenset({
        TypeKind.INT, TypeKind.UINT, TypeKind.FLOAT, TypeKind.BOOL, TypeKind.STRING,
        TypeKind.INT8, TypeKind.INT16, TypeKind.INT32, TypeKind.INT64,
        TypeKind.UINT8, TypeKind.UINT16, TypeKind.UINT32, TypeKind.UINT64,
    })

    def _is_builtin_interp_type(self, saw_type: SawType) -> bool:
        """Whether an interpolation piece uses the builtin fast lowering (design
        56). None is treated as builtin so callers with unresolved types keep the
        old <?>-fallback behaviour rather than attempting a Printable dispatch. A
        type alias flows to its underlying type (a `type MyInt = Int` stays a
        builtin fast path)."""
        if saw_type is None:
            return True
        resolved = self._resolve_type_alias(saw_type)
        return resolved.kind in self._BUILTIN_INTERP_KINDS

    def _emit_to_string(self, value, saw_type: SawType):
        """Render a builtin (primitive / String) value to an owned Saw String
        (design 56 `to_string`). Reuses the interpolation `_value_to_string`
        C-string rendering, then copies the bytes into a fresh refcount=1 String
        via `__saw_string_from_bytes` — so the result never aliases the receiver
        (a String receiver is duplicated, not shared)."""
        i8ptr = ir.IntType(8).as_pointer()
        if saw_type is not None and saw_type.kind == TypeKind.STRING:
            c_ptr = value
            length = self.builder.call(self.functions["__saw_string_len"], [value],
                                       name="ts_len")
        else:
            c_ptr = self._value_to_string(value, saw_type)
            strlen_fn = self._libc_func("strlen", self.int_type, [i8ptr])
            length = self.builder.call(strlen_fn, [c_ptr], name="ts_len")
        return self.builder.call(self.functions["__saw_string_from_bytes"],
                                 [c_ptr, length], name="ts_str")

    def _emit_format(self, value, saw_type: SawType, sb_ptr):
        """Stream a builtin value's rendering into a StringBuilder (design 56
        `format`). Renders to an owned String, then appends it through
        `StringBuilder.append(String)` (always emitted — StringBuilder is a
        non-generic std extension). `sb_ptr` is the `&var StringBuilder`
        receiver pointer that `append`'s `&var self` expects."""
        from codegen.mangle import mangle_overload
        s = self._emit_to_string(value, saw_type)
        append_sym = mangle_overload("StringBuilder_append",
                                     [SawType(TypeKind.STRING)])
        self.builder.call(self.functions[append_sym], [sb_ptr, s])

    def visit_Identifier(self, expr: Identifier):
        if expr.name not in self.variables:
            # Module-level static (design 41): load through its global.
            if expr.name in self.static_globals:
                gv = self.static_globals[expr.name]
                return self.builder.load(gv, name=expr.name)
            raise ValueError(f"Undefined variable: {expr.name}")

        # Check if this is a reference type - if so, auto-dereference
        var_type = self.variable_types.get(expr.name)
        if var_type and var_type.kind == TypeKind.REFERENCE:
            # `&any Trait` (design 51) is a FAT POINTER, not a thin pointer: the
            # alloca holds the two-word value directly, so a single load yields it
            # (no second deref — the fat struct is not a pointer to load through).
            if (var_type.inner_type is not None
                    and var_type.inner_type.kind == TypeKind.EXISTENTIAL):
                return self.builder.load(self.variables[expr.name], name=expr.name)
            # For references, the alloca holds a pointer to the actual data
            # Load the pointer, then load the value through it
            ref_ptr = self.builder.load(self.variables[expr.name], name=f"{expr.name}_ref")
            return self.builder.load(ref_ptr, name=expr.name)

        return self.builder.load(self.variables[expr.name], name=expr.name)

    def visit_BinaryOp(self, expr: BinaryOp):
        return self._generate_binary_op(expr)

    def visit_UnaryOp(self, expr: UnaryOp):
        return self._generate_unary_op(expr)

    def visit_MoveExpr(self, expr: MoveExpr):
        return self._generate_move_expr(expr)

    def visit_ReferenceExpr(self, expr: ReferenceExpr):
        return self._generate_reference_expr(expr)

    def visit_CastExpr(self, expr: CastExpr):
        return self._generate_cast_expr(expr)

    def visit_UnsafeExpr(self, expr):
        # design 81: `unsafe` is a pure type-checker visibility marker — it emits
        # exactly the inner expression's code.
        return self._generate_expression(expr.expression,
                                         need_result=getattr(self, '_need_result', True))

    def visit_FunctionCall(self, expr: FunctionCall):
        return self._generate_function_call(expr)

    def visit_IfExpr(self, expr: IfExpr):
        return self._generate_if_expression(expr)

    def visit_IfLetExpr(self, expr: IfLetExpr):
        return self._generate_if_let_expression(expr)

    def visit_TupleLiteral(self, expr: TupleLiteral):
        return self._generate_tuple_literal(expr)

    def visit_TupleIndex(self, expr: TupleIndex):
        return self._generate_tuple_index(expr)

    def visit_ArrayLiteral(self, expr: ArrayLiteral):
        return self._generate_array_literal(expr)

    def visit_MapLiteral(self, expr):
        return self._generate_map_literal(expr)

    def visit_SetLiteral(self, expr):
        return self._generate_set_literal(expr)

    def visit_ArrayIndex(self, expr: ArrayIndex):
        return self._generate_array_index(expr)

    def visit_MemberAccess(self, expr: MemberAccess):
        return self._generate_member_access(expr)

    def visit_StructInit(self, expr: StructInit):
        return self._generate_struct_init(expr)

    def visit_NoneLiteral(self, expr: NoneLiteral):
        return self._generate_none_literal(expr)

    def visit_ForceUnwrap(self, expr: ForceUnwrap):
        return self._generate_force_unwrap(expr)

    def visit_NilCoalesce(self, expr: NilCoalesce):
        return self._generate_nil_coalesce(expr)

    def visit_OptionalChain(self, expr: OptionalChain):
        return self._generate_optional_chain(expr)

    def visit_TryExpr(self, expr: TryExpr):
        return self._generate_try_expr(expr)

    def visit_TryCatchExpr(self, expr: TryCatchExpr):
        return self._generate_try_catch_expr(expr)

    def visit_MethodCall(self, expr: MethodCall):
        return self._generate_method_call(expr)

    def visit_SelfExpr(self, expr: SelfExpr):
        return self._generate_self_expr(expr)

    def visit_EnumInit(self, expr: EnumInit):
        return self._generate_enum_init(expr)

    def visit_MatchExpr(self, expr: MatchExpr):
        return self._generate_match_expr(expr)

    def visit_WhileExpr(self, expr: WhileExpr):
        return self._generate_while_expr_value(expr)

    def visit_ForLoop(self, expr: ForLoop):
        return self._generate_for_loop_value(expr)

    def visit_ClosureExpr(self, expr: ClosureExpr):
        return self._generate_closure(expr)

    # Operator methods moved to codegen_operators.py (OperatorsMixin)

    # Function call methods moved to codegen_calls.py (CallsMixin)
    # Conditional methods moved to codegen_conditionals.py (ConditionalsMixin)
    # Collection methods moved to codegen_collections.py (CollectionsMixin)
    # Struct methods moved to codegen_structs.py (StructsMixin)
    # Optional methods moved to codegen_optionals.py (OptionalsMixin)
    # Method call methods moved to codegen_calls.py (CallsMixin)
    # Enum init moved to codegen_calls.py (CallsMixin)
    # Match expression moved to codegen_match.py (MatchMixin)
    # Closure methods moved to codegen_closures.py (ClosuresMixin)

    def _run_optimization_passes(self, mod, target_machine):
        """Run a default O1-level module pipeline on a parsed binding module.

        Uses llvmlite 0.48's new pass manager (the legacy PassManagerBuilder
        was removed in this release). speed_level=1 selects the O1 default
        pipeline, which includes mem2reg/SROA (promoting the entry-block allocas
        into SSA registers), instcombine, simplifycfg, GVN, etc. Mutates `mod`
        in place.
        """
        pto = binding.create_pipeline_tuning_options(speed_level=1)
        pb = binding.create_pass_builder(target_machine, pto)
        mpm = pb.getModulePassManager()
        mpm.run(mod, pb)

    def _make_target_machine(self):
        """Create a target machine for the configured triple (default = host).

        Used by both IR optimization and object emission so `--target` flows
        through to the emitted object and the optimization pipeline.

        Hosted builds request the PIC relocation model: modern Linux toolchains
        (ubuntu-latest) link PIE by default, and LLVM's default reloc for
        x86_64-linux is non-PIC — a bare `clang obj.o -o exe` then fails with
        "relocation R_X86_64_32 against ... can not be used when making a PIE
        object". PIC links cleanly as PIE, and macOS is always PIC so this is a
        no-op there. Freestanding/embedded keeps the LLVM default (bare-metal
        links its own way via a linker script; PIC is usually wrong there).
        """
        target = binding.Target.from_triple(self.triple)
        if self.freestanding:
            return target.create_target_machine()
        return target.create_target_machine(reloc='pic')

    def emit_ir(self, optimize: bool = True) -> str:
        """Return the module's LLVM IR as text.

        When optimize is True the IR is run through the O1 pipeline first, so
        the emitted IR reflects what actually gets compiled (allocas promoted,
        dead code removed). With -O0 the raw generated IR is returned.
        """
        llvm_ir = str(self.module)
        if not optimize:
            return llvm_ir
        mod = binding.parse_assembly(llvm_ir)
        mod.verify()
        target_machine = self._make_target_machine()
        self._run_optimization_passes(mod, target_machine)
        return str(mod)

    def compile_to_object(self, output_path: str, optimize: bool = True):
        """Compile the module to an object file.

        By default runs the O1 optimization pipeline (mem2reg/SROA + friends)
        before emitting object code; pass optimize=False (sawc -O0) to skip it
        for debugging raw codegen output.
        """
        llvm_ir = str(self.module)

        # Parse the IR
        mod = binding.parse_assembly(llvm_ir)
        mod.verify()

        # Create target machine (honours --target)
        target_machine = self._make_target_machine()

        # Run the optimization pipeline (mem2reg/SROA require entry-block allocas)
        if optimize:
            self._run_optimization_passes(mod, target_machine)

        # Emit object code
        with open(output_path, 'wb') as f:
            f.write(target_machine.emit_object(mod))
