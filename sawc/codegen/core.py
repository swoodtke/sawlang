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
import copy


class CodeGenerator(ResultsMixin, MatchMixin, StructsMixin, CollectionsMixin, CallsMixin, OperatorsMixin, StatementsMixin, MethodsMixin, LoopsMixin, ConditionalsMixin, OptionalsMixin, ClosuresMixin, GenericsMixin, TypesMixin, ResourcesMixin):
    def __init__(self, namespace: Namespace, target_triple: Optional[str] = None,
                 freestanding: bool = False):
        # Unified namespace from type checker (Phase 0 of module system)
        self.namespace = namespace

        # Profile flag (design 19/20): freestanding emits the runtime seams as
        # declarations only (no hosted libc-backed defaults) and gates hosted
        # facilities (Float printing, hosted std modules).
        self.freestanding = freestanding

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

        # Create module
        self.module = ir.Module(name="saw_module")
        self.module.triple = self.triple

        # Create target data for sizeof calculations
        target = binding.Target.from_triple(self.triple)
        target_machine = target.create_target_machine()
        self.target_data = binding.create_target_data(str(target_machine.target_data))
        # When a triple is given explicitly, pin the module data layout so the
        # emitted object and compile-time sizeof() agree for that target. The
        # default (host) path leaves data_layout unset to stay byte-identical to
        # the pre-existing output.
        if self._explicit_target:
            self.module.data_layout = str(target_machine.target_data)

        # Builder will be set when generating function bodies
        self.builder: ir.IRBuilder = None

        # Symbol table for variables (name -> alloca instruction)
        self.variables: dict = {}

        # Function table
        self.functions: dict = {}

        # Struct types (name -> (LLVM type, field_order))
        self.struct_types: dict = {}

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

        # Resource management: variable lifetime tracking
        # Stack of scopes, each scope is a list of (var_name, saw_type) for variables needing cleanup
        self.cleanup_stack: List[List[tuple[str, SawType]]] = []
        # Cache: type_name -> cleanup behavior ('none', 'deinit', 'implicit_copy', 'no_copy')
        self.type_cleanup_behavior: dict[str, str] = {}
        # Cache: canonical type symbol -> whether the aggregate has any field/
        # payload that itself needs cleanup (drop glue for structs that hold
        # cleanup-needing fields but declare no deinit -- e.g. only String fields).
        self.type_field_cleanup: dict[str, bool] = {}
        # Track moved variables - these should not be cleaned up or accessed
        self.moved_variables: set[str] = set()

        # Statement-scoped temporaries (item 4): owned Deinit-needing values
        # produced mid-statement that are neither bound, returned, nor
        # transferred onward (e.g. the receiver of `makeResource().use()`).
        # None outside a statement; a list (LIFO drop at statement end) while a
        # full statement is being generated. Managed by `_generate_statement`.
        self.statement_temps: Optional[List[tuple]] = None

        # Extern functions that return optionals (need NULL check at call site)
        # Maps function name -> inner SawType (unwrapped from optional)
        self.extern_optional_returns: dict[str, SawType] = {}

        # Current return type (for implicit optional wrapping)
        self.current_return_type: Optional[SawType] = None

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

    def _entry_alloca(self, llvm_type, name=""):
        """Create an alloca in the current function's entry block.

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

    def _saw_string_header_ptrs(self, builder, p):
        """Return (block_start_i8ptr, refcount_i64ptr, len_i64ptr) for a String
        bytes pointer `p`."""
        i64 = ir.IntType(64)
        i64ptr = i64.as_pointer()
        block = builder.gep(p, [ir.Constant(i64, -16)], inbounds=True, name="hdr")
        rc_ptr = builder.bitcast(block, i64ptr, name="rc_ptr")
        len_raw = builder.gep(p, [ir.Constant(i64, -8)], inbounds=True)
        len_ptr = builder.bitcast(len_raw, i64ptr, name="len_ptr")
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
        i64 = ir.IntType(64)
        void = ir.VoidType()

        saw_alloc = ir.Function(self.module, ir.FunctionType(i8ptr, [i64, i64]),
                                name="saw_alloc")
        saw_dealloc = ir.Function(self.module, ir.FunctionType(void, [i8ptr, i64, i64]),
                                  name="saw_dealloc")
        saw_write = ir.Function(self.module, ir.FunctionType(void, [i8ptr, i64]),
                                name="saw_write")
        saw_panic = ir.Function(self.module, ir.FunctionType(void, [i8ptr, i64]),
                                name="saw_panic")
        saw_panic.attributes.add("noreturn")

        self.functions["saw_alloc"] = saw_alloc
        self.functions["saw_dealloc"] = saw_dealloc
        self.functions["saw_write"] = saw_write
        self.functions["saw_panic"] = saw_panic
        self.saw_write = saw_write
        self.saw_panic = saw_panic

        if self.freestanding:
            # Declarations only; the environment supplies the definitions.
            for fn in (saw_alloc, saw_dealloc, saw_write, saw_panic):
                fn.linkage = "external"
            return

        # ---- hosted weak definitions ----------------------------------------
        for fn in (saw_alloc, saw_dealloc, saw_write, saw_panic):
            fn.linkage = "weak"

        malloc_fn = self._libc_func("malloc", i8ptr, [i64])
        free_fn = self._libc_func("free", void, [i8ptr])

        # saw_alloc: malloc(size). `align` is ignored: malloc guarantees an
        # alignment of at least alignof(max_align_t) (>= 16 on the targets we
        # support), which covers every Saw allocation today.
        b = ir.IRBuilder(saw_alloc.append_basic_block("entry"))
        b.ret(b.call(malloc_fn, [saw_alloc.args[0]]))

        # saw_dealloc: free(ptr). `size`/`align` are ignored by the libc default.
        b = ir.IRBuilder(saw_dealloc.append_basic_block("entry"))
        b.call(free_fn, [saw_dealloc.args[0]])
        b.ret_void()

        # saw_write: fwrite(ptr, 1, len, stdout). Routing through C stdio (rather
        # than a raw write(2)) keeps print output on the same buffered stream as
        # the printf-based Float path, so interleaved int/float prints keep their
        # program order and flush semantics byte-for-byte.
        fwrite_fn = self._libc_func("fwrite", i64, [i8ptr, i64, i64, i8ptr])
        stdout_sym = "__stdoutp" if self._is_apple_triple() else "stdout"
        stdout_g = ir.GlobalVariable(self.module, i8ptr, name=stdout_sym)
        stdout_g.linkage = "external"
        b = ir.IRBuilder(saw_write.append_basic_block("entry"))
        stream = b.load(stdout_g, name="stdout")
        b.call(fwrite_fn, [saw_write.args[0], ir.Constant(i64, 1),
                           saw_write.args[1], stream])
        b.ret_void()

        # saw_panic: saw_write(msg, len) then abort(). Marked noreturn.
        abort_fn = self.abort
        b = ir.IRBuilder(saw_panic.append_basic_block("entry"))
        b.call(saw_write, [saw_panic.args[0], saw_panic.args[1]])
        b.call(abort_fn, [])
        b.unreachable()

    def _is_apple_triple(self) -> bool:
        t = (self.triple or "").lower()
        return "apple" in t or "darwin" in t or "macos" in t or "ios" in t

    def _declare_print_runtime(self):
        """Emit __saw_print_i64: format a signed 64-bit integer as decimal plus a
        trailing newline, then emit it with a single saw_write.

        This replaces printf("%lld\\n", n) for the whole integer family. Callers
        first widen the value to i64 with exactly the sign-/zero-extension the old
        printf path used (sext for signed, zext for unsigned narrower than 64),
        so the i64 seen here matches %lld's argument bit-for-bit; formatting it as
        signed decimal therefore reproduces printf output byte-for-byte across the
        full i64 range, INT64_MIN included.

        INT64_MIN handling: the magnitude is computed as an *unsigned* value
        (`select(neg, 0 - n, n)` — the wrapping negation of 0x8000...0 is itself,
        which read unsigned is 9223372036854775808), and digits are extracted with
        unsigned udiv/urem, so no signed overflow occurs.
        """
        i8 = ir.IntType(8)
        i8ptr = i8.as_pointer()
        i64 = ir.IntType(64)
        void = ir.VoidType()

        fn = ir.Function(self.module, ir.FunctionType(void, [i64]),
                         name="__saw_print_i64")
        self.functions["__saw_print_i64"] = fn
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
        neg = b.icmp_signed('<', n, ir.Constant(i64, 0), name="neg")
        mag = b.select(neg, b.sub(ir.Constant(i64, 0), n), n, name="mag")
        b.branch(loop)

        b = ir.IRBuilder(loop)
        m = b.phi(i64, name="m")
        writep = b.phi(i8ptr, name="writep")
        m.add_incoming(mag, entry)
        writep.add_incoming(nlpos, entry)
        digit = b.urem(m, ir.Constant(i64, 10), name="digit")
        ch = b.trunc(b.add(digit, ir.Constant(i64, ord('0'))), i8, name="ch")
        newwritep = b.gep(writep, [ir.Constant(i64, -1)], inbounds=True, name="w")
        b.store(ch, newwritep)
        m2 = b.udiv(m, ir.Constant(i64, 10), name="m2")
        m.add_incoming(m2, loop)
        writep.add_incoming(newwritep, loop)
        done = b.icmp_unsigned('==', m2, ir.Constant(i64, 0), name="done")
        b.cbranch(done, after, loop)

        b = ir.IRBuilder(after)
        # newwritep points at the most significant digit. Prepend '-' if negative.
        signp = b.gep(newwritep, [ir.Constant(i64, -1)], inbounds=True, name="signp")
        b.store(ir.Constant(i8, ord('-')), signp)
        startp = b.select(neg, signp, newwritep, name="startp")
        length = b.sub(b.ptrtoint(endp, i64), b.ptrtoint(startp, i64), name="len")
        b.call(self.functions["saw_write"], [startp, length])
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
        i64 = ir.IntType(64)
        void = ir.VoidType()
        null = ir.Constant(i8ptr, None)

        # String buffers now route through the seams (design 20 item 1) rather
        # than libc malloc/free directly. memcpy stays a libc/compiler builtin
        # (it is not a seam and is available freestanding via compiler-rt).
        saw_alloc_fn = self.functions["saw_alloc"]
        saw_dealloc_fn = self.functions["saw_dealloc"]
        memcpy_fn = self._libc_func("memcpy", i8ptr, [i8ptr, i8ptr, i64])
        align16 = ir.Constant(i64, 16)

        # ---- __saw_string_retain(i8* s) -------------------------------------
        fn = ir.Function(self.module, ir.FunctionType(void, [i8ptr]),
                         name="__saw_string_retain")
        self.functions["__saw_string_retain"] = fn
        s = fn.args[0]; s.name = "s"
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        with b.if_then(b.icmp_unsigned('!=', s, null)):
            _, rc_ptr, _ = self._saw_string_header_ptrs(b, s)
            rc = b.load(rc_ptr, name="rc")  # plain load: immortal check first
            with b.if_then(b.icmp_signed('!=', rc, ir.Constant(i64, -1))):
                # a live reference keeps the object alive; relaxed is enough
                b.atomic_rmw('add', rc_ptr, ir.Constant(i64, 1), ordering='monotonic')
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
            with b.if_then(b.icmp_signed('!=', rc, ir.Constant(i64, -1))):
                old = b.atomic_rmw('sub', rc_ptr, ir.Constant(i64, 1),
                                   ordering='release')
                with b.if_then(b.icmp_signed('==', old, ir.Constant(i64, 1))):
                    # last owner observed count->0: order every other thread's
                    # final reads before the free, then free the whole block.
                    b.fence(ordering='acquire')
                    # dealloc size = 16 (header) + len + 1 (NUL); len lives at
                    # ptr-8, so it is always available at the free site.
                    _, _, len_ptr = self._saw_string_header_ptrs(b, s)
                    slen = b.load(len_ptr, name="len")
                    total = b.add(slen, ir.Constant(i64, 17), name="dealloc_size")
                    b.call(saw_dealloc_fn, [block, total, align16])
        b.ret_void()

        # ---- __saw_string_alloc(i64 len) -> i8*  (NULL on OOM) ---------------
        fn = ir.Function(self.module, ir.FunctionType(i8ptr, [i64]),
                         name="__saw_string_alloc")
        self.functions["__saw_string_alloc"] = fn
        length = fn.args[0]; length.name = "len"
        entry = fn.append_basic_block("entry")
        oom = fn.append_basic_block("oom")
        ok = fn.append_basic_block("ok")
        b = ir.IRBuilder(entry)
        total = b.add(length, ir.Constant(i64, 17), name="total")  # 16 hdr + len + NUL
        block = b.call(saw_alloc_fn, [total, align16], name="block")
        b.cbranch(b.icmp_unsigned('==', block, null), oom, ok)
        b = ir.IRBuilder(oom)
        b.ret(null)
        b = ir.IRBuilder(ok)
        i64ptr = i64.as_pointer()
        rc_ptr = b.bitcast(block, i64ptr, name="rc_ptr")
        b.store(ir.Constant(i64, 1), rc_ptr)
        len_raw = b.gep(block, [ir.Constant(i64, 8)], inbounds=True)
        len_ptr = b.bitcast(len_raw, i64ptr, name="len_ptr")
        b.store(length, len_ptr)
        bytes_ptr = b.gep(block, [ir.Constant(i64, 16)], inbounds=True, name="bytes")
        nul_ptr = b.gep(bytes_ptr, [length], inbounds=True, name="nul")
        b.store(ir.Constant(i8, 0), nul_ptr)
        b.ret(bytes_ptr)

        # ---- __saw_string_from_bytes(i8* src, i64 len) -> i8* ----------------
        fn = ir.Function(self.module, ir.FunctionType(i8ptr, [i8ptr, i64]),
                         name="__saw_string_from_bytes")
        self.functions["__saw_string_from_bytes"] = fn
        src = fn.args[0]; src.name = "src"
        length = fn.args[1]; length.name = "len"
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        bytes_ptr = b.call(self.functions["__saw_string_alloc"], [length], name="dst")
        with b.if_then(b.icmp_unsigned('!=', bytes_ptr, null)):
            b.call(memcpy_fn, [bytes_ptr, src, length])
        b.ret(bytes_ptr)

        # ---- __saw_string_len(i8* s) -> i64 ---------------------------------
        fn = ir.Function(self.module, ir.FunctionType(i64, [i8ptr]),
                         name="__saw_string_len")
        self.functions["__saw_string_len"] = fn
        s = fn.args[0]; s.name = "s"
        entry = fn.append_basic_block("entry")
        null_b = fn.append_basic_block("is_null")
        ok = fn.append_basic_block("ok")
        b = ir.IRBuilder(entry)
        b.cbranch(b.icmp_unsigned('==', s, null), null_b, ok)
        b = ir.IRBuilder(null_b)
        b.ret(ir.Constant(i64, 0))
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
        """
        i64 = ir.IntType(64)
        i64ptr = i64.as_pointer()
        void = ir.VoidType()

        # __saw_atomic_add_i64(i64* ptr, i64 delta) -> i64 (old value), monotonic
        fn = ir.Function(self.module, ir.FunctionType(i64, [i64ptr, i64]),
                         name="__saw_atomic_add_i64")
        self.functions["__saw_atomic_add_i64"] = fn
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        old = b.atomic_rmw('add', fn.args[0], fn.args[1], ordering='monotonic')
        b.ret(old)

        # __saw_atomic_sub_i64_release(i64* ptr, i64 delta) -> i64 (old), release
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
        hdr_type = ir.LiteralStructType([ir.IntType(64), ir.IntType(64), arr_type])

        name = f".sawstr.{self.string_counter}"
        self.string_counter += 1
        g = ir.GlobalVariable(self.module, hdr_type, name=name)
        g.linkage = 'private'
        g.global_constant = True
        g.initializer = ir.Constant(hdr_type, [
            ir.Constant(ir.IntType(64), -1),   # immortal sentinel
            ir.Constant(ir.IntType(64), n),
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
        self._declare_print_runtime()
        self._declare_atomic_runtime()

        # Store generic and specialized extensions FIRST
        # This must happen before struct registration since structs with generic
        # field types (e.g., Vector<Foo>) trigger monomorphization which needs
        # access to generic extensions.
        for extension in program.extensions:
            if extension.type_params:
                spec_key = self._get_extension_specialization(extension)
                if spec_key:
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
                # Store generic function for later instantiation
                self.generic_functions[func.name] = func
            else:
                self._declare_function(func)

        # Declare non-generic extension methods
        for extension in program.extensions:
            if not extension.type_params:
                self._declare_extension_methods(extension)

        # Fifth pass: generate function bodies (skip generic functions)
        for func in program.functions:
            if not func.type_params:
                self._generate_function(func)

        # Generate extension method bodies
        for extension in program.extensions:
            self._generate_extension_methods(extension)

        # Generate pending monomorphized method bodies
        # These were queued during monomorphization to ensure all signatures exist first
        self._generate_pending_method_bodies()

        return str(self.module)

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
                variant_types = [self._get_llvm_type(typ) for _, typ in variant.associated_types]
                # Create a struct to hold the associated values
                if variant_types:
                    variant_struct = ir.LiteralStructType(variant_types)
                    # Get size of the variant struct in bytes
                    # For simplicity, we calculate a conservative size
                    # In a real implementation, we'd use LLVM's DataLayout
                    size = sum(self._estimate_type_size(t) for t in variant_types)
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

    def _declare_function(self, func: Function, name_override: str = None):
        """Declare a function. If name_override is provided, use it instead of func.name."""
        func_name = name_override if name_override else func.name
        param_types = [self._get_llvm_type(p.type) for p in func.parameters]
        return_type = self._get_llvm_type(func.return_type)

        # Main function should return int for proper exit code
        if func_name == "main" and func.return_type.kind == TypeKind.VOID:
            return_type = ir.IntType(32)

        func_type = ir.FunctionType(return_type, param_types)
        llvm_func = ir.Function(self.module, func_type, name=func_name)
        self.functions[func_name] = llvm_func
        # Function return types are now in namespace

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
            # Create mangled name
            if method.is_init:
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
                if extension.struct_name == "String":
                    self_llvm_type = ir.IntType(8).as_pointer()  # String is i8*
                else:
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
        return ir.Constant(ir.IntType(64), expr.value)

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
        i64 = ir.IntType(64)

        # Convert every interpolated expression to a C string pointer once; the
        # same pointers are reused for both the length pass and the build pass.
        piece_ptrs = []
        for sub_expr in expr.expressions:
            value = self._generate_expression(sub_expr)
            saw_type = self._expr_type(sub_expr)
            piece_ptrs.append(self._value_to_string(value, saw_type))

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

    def visit_Identifier(self, expr: Identifier):
        if expr.name not in self.variables:
            raise ValueError(f"Undefined variable: {expr.name}")

        # Check if this is a reference type - if so, auto-dereference
        var_type = self.variable_types.get(expr.name)
        if var_type and var_type.kind == TypeKind.REFERENCE:
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
        """
        target = binding.Target.from_triple(self.triple)
        return target.create_target_machine()

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
