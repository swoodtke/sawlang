#!/usr/bin/env python3
"""
Saw Language Compiler
A simple compiler for the Saw programming language.

Usage:
    sawc <input.saw> [-o output]

This compiles a .saw file to a native executable.
"""

import argparse
import subprocess
import sys
import os
import tempfile

from lexer import Lexer
from parser import Parser
from codegen import CodeGenerator
from errors import (ErrorReporter, ErrorKind, WARNING_CATEGORIES,
                    enable_warnings)
from typechecker import TypeChecker
from module_resolver import ModuleResolver, ModulePathError


def parse_source(source: str, source_path: str, verbose: bool = False):
    """Parse a Saw source file and return the AST."""
    # Lexical analysis
    try:
        lexer = Lexer(source)
        tokens = lexer.tokenize()
    except SyntaxError as e:
        print(f"\033[1;31merror\033[0m: {e}", file=sys.stderr)
        sys.exit(1)

    # Parsing
    try:
        parser = Parser(tokens, source_file=source_path,
                        doc_comments=lexer.doc_comments)
        program = parser.parse()
    except SyntaxError as e:
        print(f"\033[1;31merror\033[0m: {e}", file=sys.stderr)
        sys.exit(1)

    # design 141: lower `borrows` declarations to their window-closure form
    # before anything downstream sees them, so registration, inference,
    # monomorphization and codegen all handle an ordinary generic method and
    # need to know nothing about places. Every compilation path funnels through
    # here — builtins, std, imported modules and the entry file — which is why
    # the transform lives here rather than at any one of those call sites.
    # `tools/dump_ast.py` builds its own parser and so still dumps the AUTHORED
    # form, which is what a parser-stage oracle should show.
    from place_transform import transform_places
    place_reporter = ErrorReporter(source, source_path)
    transform_places(program, place_reporter, source_path)
    if place_reporter.has_errors():
        place_reporter.print_all()
        sys.exit(1)

    return program


# Hosted-only std modules (design 19 layering): they depend on libc/OS and are
# excluded from the freestanding profile. Core + alloc-layer modules (string,
# vector, map, data, stringbuilder, path) depend only on the runtime seams and
# remain available freestanding.
HOSTED_STD_MODULES = {"file", "process", "env", "directory", "time", "net"}

# ---------------------------------------------------------------------------
# Prelude discipline (design 82 Part B).
#
# The prelude — the std names auto-visible without an `import` — is a CURATED
# core, not "all of std auto-merged". Every std symbol stays compiler-known for
# codegen; only the prelude set is injected into a user module's namespace. The
# rest requires an explicit `import std.<module>` (or `import std.<module>.{X}`).
#
# We define the partition by its complement: the IMPORT-REQUIRED std modules
# (their entire top-level surface needs importing) plus a small set of
# import-required symbols carved out of an otherwise-prelude file. Everything
# else — core containers/wrappers/traits, the systems primitives, and the
# structural types the compiler references implicitly (Range, Ordering, Hasher,
# TaskHandle, AllocError, the iterator/slot structs) — stays prelude. This
# realizes design 82's allowlist: the curated core is auto-visible; File,
# Data, Channel, Mutex, Duration/Instant, IoError/Utf8Error, and the whole net
# surface are import-required, so a user type named `IoError`/`File` no longer
# collides with the prelude.
IMPORT_REQUIRED_STD_MODULES = {
    "file", "directory", "path", "data", "channel", "mutex", "time",
    "net", "process", "env", "task", "fixedbuf", "cbor",
}
# Symbols carved out of an otherwise-prelude std file (the file stays prelude
# for its other symbols; only these named ones require an import).
IMPORT_REQUIRED_STD_SYMBOLS = {
    "Utf8Error": "string",
}


def std_source_paths(freestanding: bool = False, runtime_build: bool = False):
    """The stdlib sources a compile under these flags reads, in load order.

    One source of truth for two callers: `load_builtins` parses them, and the
    design-168 std cache hashes them into its key. A key computed from a
    different file set than the one that was parsed is a stale-cache miscompile,
    so the two must not be able to drift.
    """
    sawc_dir = os.path.dirname(__file__)
    paths = []

    # builtin.saw first (core traits).
    builtin_path = os.path.join(sawc_dir, 'builtin.saw')
    if os.path.exists(builtin_path):
        paths.append(builtin_path)

    # std/ is skipped entirely in runtime-build mode.
    std_dir = os.path.join(sawc_dir, 'std')
    if not runtime_build and os.path.isdir(std_dir):
        std_files = sorted(f for f in os.listdir(std_dir) if f.endswith('.saw'))
        if freestanding:
            std_files = [f for f in std_files
                         if os.path.splitext(f)[0] not in HOSTED_STD_MODULES]
        paths.extend(os.path.join(std_dir, f) for f in std_files)

    return paths


def load_builtins(verbose: bool = False, freestanding: bool = False,
                  runtime_build: bool = False):
    """Load and parse the builtin.saw file and all std/*.saw files.

    In the freestanding profile the hosted-only std modules (file, process, env,
    directory) are not loaded, so their libc/OS externs are never compiled in.

    In runtime-build mode (design 113b) NO std module is loaded: a runtime sits
    BELOW the stdlib (it implements the seams the stdlib rests on), declares its
    own libc externs, and uses only the core builtins (UnsafePointer/Atomic/
    Optional/…). Skipping std also avoids clashing with std's own extern
    declarations of libc symbols (e.g. `malloc`).
    """
    from ast_nodes import Program

    combined_ast = None
    # design 121: builtin.saw + every std file merge into ONE Program, so each
    # file's `//!` module doc is kept here, keyed by path, for `--emit-docs`.
    file_module_docs = {}

    for filepath in std_source_paths(freestanding, runtime_build):
        with open(filepath, 'r') as f:
            source = f.read()
        if verbose:
            print(f"  Loading {os.path.basename(filepath)}...")
        file_ast = parse_source(source, filepath, verbose)
        file_module_docs[filepath] = file_ast.module_doc
        if combined_ast is None:
            combined_ast = file_ast
        else:
            combined_ast = Program(
                structs=combined_ast.structs + file_ast.structs,
                functions=combined_ast.functions + file_ast.functions,
                extensions=combined_ast.extensions + file_ast.extensions,
                enums=combined_ast.enums + file_ast.enums,
                traits=combined_ast.traits + file_ast.traits,
                type_definitions=combined_ast.type_definitions + file_ast.type_definitions,
                extern_blocks=combined_ast.extern_blocks + file_ast.extern_blocks,
                statics=getattr(combined_ast, 'statics', []) + getattr(file_ast, 'statics', []),
                static_asserts=getattr(combined_ast, 'static_asserts', []) + getattr(file_ast, 'static_asserts', []),
                line=combined_ast.line,
                column=combined_ast.column
            )

    if combined_ast is not None:
        combined_ast.file_module_docs = file_module_docs
    return combined_ast


def merge_programs(builtin_ast, user_ast):
    """Merge builtin definitions with user program."""
    if builtin_ast is None:
        return user_ast

    from ast_nodes import Program

    return Program(
        structs=builtin_ast.structs + user_ast.structs,
        functions=builtin_ast.functions + user_ast.functions,
        extensions=builtin_ast.extensions + user_ast.extensions,
        enums=builtin_ast.enums + user_ast.enums,
        traits=builtin_ast.traits + user_ast.traits,
        type_definitions=builtin_ast.type_definitions + user_ast.type_definitions,
        extern_blocks=builtin_ast.extern_blocks + user_ast.extern_blocks,
        statics=getattr(builtin_ast, 'statics', []) + getattr(user_ast, 'statics', []),
        # Preserve user imports, module declarations, and exports (builtins don't have these)
        imports=getattr(user_ast, 'imports', []),
        module_decls=getattr(user_ast, 'module_decls', []),
        exports=getattr(user_ast, 'exports', []),
        static_asserts=(getattr(builtin_ast, 'static_asserts', [])
                        + getattr(user_ast, 'static_asserts', [])),
        source_path=getattr(user_ast, 'source_path', None),
        module_path=getattr(user_ast, 'module_path', None),
        line=user_ast.line,
        column=user_ast.column
    )


def uses_modules(ast) -> bool:
    """Check if the program uses the module system (has imports or module declarations)."""
    return bool(getattr(ast, 'imports', []) or getattr(ast, 'module_decls', []))


def topological_sort_modules(module_map):
    """
    Topologically sort modules by their dependencies.

    Modules are sorted so that dependencies come before dependents.
    This ensures that when type-checking a module, all its imports
    have already been type-checked.

    Args:
        module_map: Dict of module_path_tuple -> AST

    Returns:
        List of module_path_tuple in dependency order
    """
    # Build dependency graph
    # For each module, find what it imports and declares
    dependencies = {}  # module_path -> set of module_paths it depends on
    for mod_path, mod_ast in module_map.items():
        deps = set()
        for imp in getattr(mod_ast, 'imports', []):
            imp_path = tuple(imp.path)
            # Handle package/parent prefixes
            if imp_path and imp_path[0] == 'package':
                imp_path = imp_path[1:]
            elif imp_path and imp_path[0] == 'parent':
                imp_path = imp_path[1:]
            if imp_path in module_map:
                deps.add(imp_path)
        # Also add external module declarations as dependencies
        # e.g., `public module lib` means this module depends on lib
        for mod_decl in getattr(mod_ast, 'module_decls', []):
            if not mod_decl.is_inline:
                decl_path = (mod_decl.name,)
                if decl_path in module_map:
                    deps.add(decl_path)
        dependencies[mod_path] = deps

    # Kahn's algorithm for topological sort
    # Count incoming edges for each node
    in_degree = {mod: 0 for mod in module_map}
    for mod, deps in dependencies.items():
        for dep in deps:
            if dep in in_degree:
                in_degree[mod] += 1

    # Start with nodes that have no dependencies
    queue = [mod for mod, degree in in_degree.items() if degree == 0]
    result = []

    while queue:
        mod = queue.pop(0)
        result.append(mod)

        # For each module that depends on this one, reduce its in-degree
        for other_mod, deps in dependencies.items():
            if mod in deps:
                in_degree[other_mod] -= 1
                if in_degree[other_mod] == 0:
                    queue.append(other_mod)

    # Check for cycles
    if len(result) != len(module_map):
        # There's a cycle - just return in arbitrary order
        # The type checker will handle any errors
        return list(module_map.keys())

    return result


def build_builtin_namespace(verbose: bool = False, freestanding: bool = False,
                            runtime_build: bool = False, builtin_ast=None,
                            target_triple: str = None):
    """Load, parse, and type-check the builtins once, returning
    ``(builtin_ast, builtin_ns)``.

    This replaces the former hand-inlined registration sequence that reached
    into the typechecker's private ``_register_*`` methods. Type-checking the
    builtins through the public ``check()`` entry point keeps a single
    registration path, and populates a namespace in which every builtin symbol
    is marked directly accessible so modules can use ``String``/``Vector``/
    ``Result`` etc. without an explicit import.

    ``builtin_ast`` hands back an ALREADY-PARSED builtin+std AST (design 146):
    the front half re-enters after a source-level transform, and re-reading
    every std file off disk to parse it a second time is both pure cost and a
    correctness hole — a transform that rewrote something in std would have its
    work thrown away. Registration is idempotent, so the reused AST is simply
    re-checked.
    """
    if builtin_ast is None:
        builtin_ast = load_builtins(verbose, freestanding, runtime_build)

    # Check the builtins with a throwaway reporter so their (absent) errors
    # never pollute user diagnostics. require_main=False: builtins are a library.
    builtin_reporter = ErrorReporter("", "builtins")
    builtin_tc = TypeChecker(builtin_reporter, freestanding=freestanding,
                             runtime_build=runtime_build,
                             target_triple=target_triple)
    builtin_tc.namespace.allow_all_access = True
    # design 82 Part B: mark this as the builtin/std check so the prelude gate and
    # the hidden-std shadow allowance are BOTH disabled while std checks itself
    # (std reaches every std symbol by construction; allow_all_access is an
    # unreliable signal because a fresh Namespace defaults it True).
    builtin_tc._checking_builtins = True
    if not builtin_tc.check(builtin_ast, require_main=False):
        # A builtin that fails to type-check is a compiler bug, not user error.
        print("\033[1;31merror\033[0m: internal compiler error: builtins failed "
              "to type-check", file=sys.stderr)
        builtin_reporter.print_all()
        sys.exit(1)

    builtin_ns = builtin_tc.namespace

    # design 82 Part B: build the (std-file -> {symbol names}) map from the AST's
    # source_file provenance, so an `import std.<module>` can re-expose exactly
    # that module's symbols and the "did you mean import" hint can name the owner.
    def _leaf_of(source_file):
        if not source_file:
            return None
        b = os.path.basename(source_file)
        return b[:-4] if b.endswith('.saw') else b

    std_file_symbols = {}      # leaf -> set(names)
    std_symbol_file = {}       # name -> leaf (first owner wins)
    for decls in (getattr(builtin_ast, 'structs', []),
                  getattr(builtin_ast, 'enums', []),
                  getattr(builtin_ast, 'functions', []),
                  getattr(builtin_ast, 'traits', []),
                  getattr(builtin_ast, 'type_definitions', [])):
        for d in decls:
            leaf = _leaf_of(getattr(d, 'source_file', None))
            if leaf is None:
                continue
            std_file_symbols.setdefault(leaf, set()).add(d.name)
            std_symbol_file.setdefault(d.name, leaf)

    def _is_prelude(name):
        """Whether a builtin/std symbol is in the auto-visible prelude."""
        if name in IMPORT_REQUIRED_STD_SYMBOLS:
            return False
        leaf = std_symbol_file.get(name)
        if leaf is not None and leaf in IMPORT_REQUIRED_STD_MODULES:
            return False
        return True

    # Only the prelude core is directly accessible; every other std symbol stays
    # registered (compiler-known for codegen + reachable via `import std.X`) but
    # is NOT injected into a user namespace without an import.
    for table in (builtin_ns.structs, builtin_ns.enums, builtin_ns.functions,
                  builtin_ns.traits, builtin_ns.type_aliases):
        for name in table:
            if _is_prelude(name):
                builtin_ns.make_accessible(name)

    builtin_ns._std_file_symbols = std_file_symbols
    builtin_ns._std_symbol_file = std_symbol_file
    builtin_ns._import_required_modules = IMPORT_REQUIRED_STD_MODULES
    builtin_ns._import_required_symbols = IMPORT_REQUIRED_STD_SYMBOLS

    # design 84: the suspending (struct, method) pairs among the builtins + std
    # (e.g. `TcpStream.read`, `TcpListener.accept`) — computed under the builtin
    # typechecker's finalized effect graph. The main compile typechecker never
    # checks std bodies (they are pre-checked here), so it cannot infer these on
    # its own; carrying the set lets the coroutine transform embed a nested
    # suspending std method called from an entry-module driven/spawned body.
    std_suspending = set()
    for ext in getattr(builtin_ast, 'extensions', []):
        sname = getattr(ext, 'struct_name', None)
        for m in ext.methods:
            node = builtin_tc._suspend_nodes.get(m.node_id)
            if node is not None and node.suspends:
                std_suspending.add((sname, m.name))
    builtin_ns._std_suspending_methods = std_suspending

    # design 121: the same question for FREE std functions (`yield_now`), so
    # `--emit-docs` can report each std item's effect. Same reason the method set
    # exists — only the builtin typechecker ever analyzes std bodies.
    std_suspending_funcs = set()
    for fn in getattr(builtin_ast, 'functions', []):
        node = builtin_tc._suspend_nodes.get(
            ("fn", getattr(fn, 'mangled_symbol', None) or fn.name))
        if node is not None and node.suspends:
            std_suspending_funcs.add(fn.name)
    builtin_ns._std_suspending_functions = std_suspending_funcs

    return builtin_ast, builtin_ns


def _prepared_builtins(verbose, freestanding, runtime_build, target_triple,
                       target_features, no_hidden_alloc, optimize):
    """The pristine `(builtin_ast, builtin_ns)` pair, from the cache or fresh.

    Called BEFORE the entry file is parsed (design 168 unit 4), and the pair it
    returns has to STAY pristine long enough to be stored: user type-checking
    mutates the shared builtin symbols (`generic_primitive_bounds.saw` adds a
    method and a conformance to the cached `Int` and `Float`) and place lowering
    rewrites std method bodies in place. So the store happens here, one statement
    after the build, and never on a re-entry.
    """
    import stdcache

    if not stdcache.enabled():
        return build_builtin_namespace(verbose, freestanding, runtime_build,
                                       target_triple=target_triple)

    key = stdcache.cache_key(
        std_source_paths(freestanding, runtime_build),
        freestanding, runtime_build, target_triple, target_features,
        no_hidden_alloc, optimize)

    restored = stdcache.load(key)
    if restored is not None:
        if verbose:
            print(f"  Builtins: restored from .build/stdcache/{key}.blob")
        return restored

    builtins = build_builtin_namespace(verbose, freestanding, runtime_build,
                                       target_triple=target_triple)
    stdcache.store(key, *builtins)
    return builtins


def _strip_line_comments(text: str) -> str:
    """Drop `//` line comments so a symbol name mentioned only in prose is not
    counted as a code reference by the std dependency scan (design 82 Part B)."""
    out = []
    for line in text.splitlines():
        i = line.find('//')
        out.append(line[:i] if i >= 0 else line)
    return '\n'.join(out)


def compute_std_codegen_exclusions(builtin_ns, import_asts):
    """design 82 Part B — which std modules are compiled into THIS program.

    Prelude std modules are always compiled. An import-required std module is
    compiled only if it is imported (any `import std.<module>`) OR referenced by
    a module that is compiled (the transitive dependency closure — e.g. `string`
    needs `data`). Everything else is EXCLUDED from codegen, so its symbols do
    not collide with a user type of the same name (the design-84 `IoError` clash).

    Returns ``(excluded_leaves, excluded_symbols)``: the std file leaves left out
    and the top-level symbol names they own.
    """
    import re
    file_symbols = getattr(builtin_ns, '_std_file_symbols', {}) or {}
    all_leaves = set(file_symbols)

    # Read the std sources (comment-stripped) once for the reference scan.
    sawc_dir = os.path.dirname(__file__)
    sources = {}
    std_dir = os.path.join(sawc_dir, 'std')
    if os.path.isdir(std_dir):
        for fn in os.listdir(std_dir):
            if fn.endswith('.saw'):
                with open(os.path.join(std_dir, fn)) as f:
                    sources[fn[:-4]] = _strip_line_comments(f.read())
    builtin_path = os.path.join(sawc_dir, 'builtin.saw')
    if os.path.exists(builtin_path):
        with open(builtin_path) as f:
            sources['builtin'] = _strip_line_comments(f.read())

    # Imported std leaves (an `import std.<leaf>...` anywhere in the program).
    imported = set()
    for ast in import_asts:
        for imp in getattr(ast, 'imports', []):
            p = getattr(imp, 'path', None) or []
            if len(p) >= 2 and p[0] == 'std':
                imported.add(p[1])

    # Base compiled set: prelude modules + imported import-required modules.
    compiled = {leaf for leaf in all_leaves
                if leaf not in IMPORT_REQUIRED_STD_MODULES}
    compiled |= (imported & all_leaves)

    # Precompile a word matcher per leaf's symbols.
    leaf_patterns = {
        leaf: re.compile('|'.join(r'\b' + re.escape(s) + r'\b'
                                  for s in syms)) if syms else None
        for leaf, syms in file_symbols.items()
    }
    # Transitive closure: pull in any module referenced by a compiled module.
    changed = True
    while changed:
        changed = False
        for leaf in all_leaves - compiled:
            pat = leaf_patterns.get(leaf)
            if pat is None:
                continue
            for c in compiled:
                src = sources.get(c)
                if src and pat.search(src):
                    compiled.add(leaf)
                    changed = True
                    break

    excluded_leaves = all_leaves - compiled
    excluded_symbols = set()
    for leaf in excluded_leaves:
        excluded_symbols |= file_symbols.get(leaf, set())
    return excluded_leaves, excluded_symbols


def _filter_std_ast(builtin_ast, excluded_leaves):
    """Return a copy of the builtin AST with every top-level declaration (and
    extension) owned by an EXCLUDED std file removed, so excluded std modules are
    not code-generated (design 82 Part B). Provenance is the decl's source_file
    leaf; anything without a std source_file is kept."""
    from ast_nodes import Program

    def _leaf(node):
        sf = getattr(node, 'source_file', None)
        if not sf:
            return None
        b = os.path.basename(sf)
        return b[:-4] if b.endswith('.saw') else b

    def keep(node):
        leaf = _leaf(node)
        return leaf is None or leaf not in excluded_leaves

    # Traits and type aliases are kept regardless of their owning file: they are
    # declaration-only (no code to emit), other std modules name them in their
    # signatures, and this filter never dropped them (they carried no
    # `source_file` until design 121 gave every declaration one).
    filtered = Program(
        structs=[s for s in builtin_ast.structs if keep(s)],
        functions=[f for f in builtin_ast.functions if keep(f)],
        extensions=[e for e in builtin_ast.extensions if keep(e)],
        enums=[e for e in builtin_ast.enums if keep(e)],
        traits=list(builtin_ast.traits),
        type_definitions=list(builtin_ast.type_definitions),
        extern_blocks=[b for b in getattr(builtin_ast, 'extern_blocks', []) if keep(b)],
        statics=[s for s in getattr(builtin_ast, 'statics', []) if keep(s)],
        static_asserts=list(getattr(builtin_ast, 'static_asserts', [])),
        line=builtin_ast.line,
        column=builtin_ast.column,
    )
    # design 121: the per-file `//!` docs survive the filter (a module that was
    # excluded from codegen simply has no declarations left to document).
    filtered.file_module_docs = getattr(builtin_ast, 'file_module_docs', {})
    return filtered


def run_codegen(codegen, ast):
    """Run code generation for `ast` (the single codegen call site).

    Codegen has ~76 bare `raise ValueError` sites (plus llvmlite failures such
    as DuplicatedNameError) that were never wrapped — unlike parser calls — so
    an internal failure printed a raw Python traceback. This single wrapper
    surfaces any such failure as a clean `internal compiler error: <message>`
    diagnostic with the standard exit code, mirroring how parse errors are
    reported. Individual raise-site message quality is out of scope.
    """
    from codegen.core import StaticAssertError, CodegenUserError
    try:
        return codegen.generate(ast)
    except StaticAssertError as e:
        # design 53: a failed/non-constant static_assert is a user compile error.
        print(f"\033[1;31merror\033[0m: {e.message}", file=sys.stderr)
        sys.exit(1)
    except CodegenUserError as e:
        # design 176: a rejected PROGRAM, anchored where it was written.
        where = f"{e.source_file}:{e.line}" if e.source_file else f"line {e.line}"
        print(f"\033[1;31merror\033[0m: {e.message}", file=sys.stderr)
        print(f"  \033[1;34m-->\033[0m {where}:{e.column}", file=sys.stderr)
        if e.hint:
            print(f"   \033[1;32mhint\033[0m: {e.hint}", file=sys.stderr)
        sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:
        if os.environ.get("SAW_DEBUG"):
            import traceback
            traceback.print_exc()
        print(f"\033[1;31merror\033[0m: internal compiler error: {e}",
              file=sys.stderr)
        sys.exit(1)


def _reject_freestanding_macho(target_triple: str = None):
    """`--freestanding` needs an ELF target (design 122 unit H).

    The freestanding profile places every function in its own `.text.<name>`
    section so `ld.lld --gc-sections` can drop the unreachable stdlib (design
    112). Mach-O does not accept that section spelling — it wants
    `__SEGMENT,__section` — and LLVM aborts the whole process with
    `LLVM ERROR: ... invalid section specifier`, leaving a 0-byte object behind.
    Catch it here, before any of that, and say what to pass instead.
    """
    import llvmlite.binding as binding
    triple = target_triple or binding.get_default_triple()
    t = triple.lower()
    if not any(k in t for k in ("apple", "darwin", "macos", "ios")):
        return
    print(f"\033[1;31merror\033[0m: `--freestanding` cannot target the Mach-O "
          f"triple `{triple}`", file=sys.stderr)
    print(f"   \033[1;32mhint\033[0m: the freestanding profile emits per-function "
          f"`.text.<name>` sections for `--gc-sections`, which Mach-O does not "
          f"support. Cross-compile to an ELF target, e.g. `--target "
          f"riscv32-unknown-none-elf` (also `aarch64-unknown-none-elf`, "
          f"`x86_64-unknown-none-elf`).", file=sys.stderr)
    sys.exit(1)


def _prepare_codegen(source_path: str, entry_ast, entry_source: str, verbose: bool = False, object_only: bool = False, target_triple: str = None, freestanding: bool = False, module_paths: dict = None, runtime_build: bool = False, docs_out: dict = None, post_transform: bool = False, target_features: str = None, parsed=None, places_lowered: bool = False, no_hidden_alloc: bool = False, runtime_provider: bool = False, builtins=None):
    """Resolve modules, load builtins, and type-check the whole program.

    This is the single front half of the compile pipeline: a plain single file
    is simply a module graph of size one (no imports, empty module map). It
    returns ``(codegen, merged_ast)`` — a ``CodeGenerator`` primed with the
    fully merged namespace and the merged AST — ready for ``run_codegen``.
    Exits the process on any type / resolution error.

    Steps:
    1. Resolve all module imports to their source files
    2. Parse imported modules and build the module map for qualified access
    3. Merge all modules with builtins for code generation
    4. Type check per-module with module-aware symbol resolution
    5. Merge namespaces and construct the code generator

    ``parsed`` is the design-146 re-entry hand-off: every AST this function
    parsed on the previous pass, so the second pass re-checks those objects
    instead of reading the same files off disk and parsing them again. A
    source-level transform runs BETWEEN the two passes (the coroutine
    transform, the place transform) and writes into these ASTs, so re-parsing
    is not merely wasted work — it silently discards the rewrite for every
    module and for std. Only ``entry_ast`` used to survive, which is why the
    coroutine transform could only ever rewrite the entry module.
    """
    from module_resolver import ModuleInfo
    from ast_nodes import Program

    # Freestanding always emits an unlinked object file; the user owns linking.
    if freestanding:
        object_only = True
        _reject_freestanding_macho(target_triple)

    # Reject imports of hosted-only std modules under the freestanding profile.
    if freestanding:
        for imp in getattr(entry_ast, 'imports', []):
            leaf = imp.path[-1] if imp.path else None
            if leaf in HOSTED_STD_MODULES and (
                    'std' in imp.path or len(imp.path) == 1):
                print(f"\033[1;31merror\033[0m: module `{'.'.join(imp.path)}` is "
                      f"hosted-only and cannot be imported in the freestanding "
                      f"profile", file=sys.stderr)
                sys.exit(1)

    if verbose:
        print("  Resolving module dependencies...")

    # Create resolver with search paths and explicit package mappings.
    source_dir = os.path.dirname(os.path.abspath(source_path))
    resolver = ModuleResolver([source_dir], module_paths=module_paths)

    # Resolve all imports and collect module ASTs
    # module_map: module_path_tuple -> AST (for qualified access)
    # design 146: on a re-entry the graph is already resolved and parsed, and
    # those ASTs are the ones the transform just rewrote — take them as they
    # stand. `resolved_modules` seeded from the map also makes the external
    # `module X` loads below no-ops, since they key off exactly that set.
    module_map = dict(parsed['module_map']) if parsed else {}
    module_sources = dict(parsed['module_sources']) if parsed else {}
    resolved_modules = set(module_map)
    pending_imports = [] if parsed else list(getattr(entry_ast, 'imports', []))

    while pending_imports:
        imp = pending_imports.pop(0)
        module_path = tuple(imp.path)

        # design 82 Part B: `import std.<module>` is a PRELUDE import — the std
        # symbols are already compiled into the builtin AST/namespace, so do NOT
        # re-resolve/re-parse the file (that would double-define every symbol).
        # The typechecker's import processing makes the requested names accessible
        # from the builtin namespace; codegen already has them.
        if imp.path and imp.path[0] == 'std':
            continue

        # Skip package/parent prefix for resolution
        if imp.path and imp.path[0] in ('package', 'parent'):
            resolved_path = resolver.resolve_import_path(imp.path, [])
            module_path = tuple(resolved_path)

        if module_path in resolved_modules:
            continue

        # Try to resolve the module
        try:
            mod_info = resolver.resolve_module(list(module_path), source_path)
        except ModulePathError as e:
            print(f"\033[1;31merror\033[0m: {e.message}", file=sys.stderr)
            sys.exit(1)
        if mod_info:
            # Load and parse the module
            resolver.load_module_source(mod_info)
            mod_ast = parse_source(mod_info.source, mod_info.source_path, verbose)
            # Track source for error reporting
            module_sources[mod_info.source_path] = mod_info.source

            if verbose:
                print(f"    Resolved: {'.'.join(module_path)} -> {mod_info.source_path}")

            module_map[module_path] = mod_ast
            resolved_modules.add(module_path)

            # Add this module's imports to pending
            for sub_imp in getattr(mod_ast, 'imports', []):
                pending_imports.append(sub_imp)

            # Also process external module declarations from this imported module
            # This enables re-exporting: if mod.saw has `public module lib`,
            # then lib.saw needs to be loaded
            mod_source_dir = os.path.dirname(mod_info.source_path)
            for mod_decl in getattr(mod_ast, 'module_decls', []):
                if not mod_decl.is_inline:
                    simple_path = (mod_decl.name,)
                    if simple_path not in resolved_modules:
                        # Look for the module file relative to the imported module
                        sub_mod_file = os.path.join(mod_source_dir, f"{mod_decl.name}.saw")
                        sub_mod_dir_file = os.path.join(mod_source_dir, mod_decl.name, "module.saw")

                        if os.path.isfile(sub_mod_file):
                            with open(sub_mod_file, 'r') as f:
                                sub_mod_source = f.read()
                            sub_mod_ast = parse_source(sub_mod_source, sub_mod_file, verbose)
                            module_sources[sub_mod_file] = sub_mod_source
                            # Register with simple path only (avoids duplicate merging)
                            module_map[(mod_decl.name,)] = sub_mod_ast
                            resolved_modules.add((mod_decl.name,))
                            if verbose:
                                print(f"    Module decl: {mod_decl.name} -> {sub_mod_file}")

                            # Recursively process imports from this module
                            for sub_imp in getattr(sub_mod_ast, 'imports', []):
                                pending_imports.append(sub_imp)
                        elif os.path.isfile(sub_mod_dir_file):
                            with open(sub_mod_dir_file, 'r') as f:
                                sub_mod_source = f.read()
                            sub_mod_ast = parse_source(sub_mod_source, sub_mod_dir_file, verbose)
                            module_sources[sub_mod_dir_file] = sub_mod_source
                            module_map[(mod_decl.name,)] = sub_mod_ast
                            resolved_modules.add((mod_decl.name,))
                            if verbose:
                                print(f"    Module decl: {mod_decl.name} -> {sub_mod_dir_file}")

                            for sub_imp in getattr(sub_mod_ast, 'imports', []):
                                pending_imports.append(sub_imp)
                        else:
                            print(f"\033[1;31merror\033[0m: module `{mod_decl.name}` not found (declared in {mod_info.source_path})", file=sys.stderr)
                            sys.exit(1)
        else:
            # Module not found - report error
            print(f"\033[1;31merror\033[0m: module `{'.'.join(module_path)}` not found", file=sys.stderr)
            sys.exit(1)

    if verbose:
        print(f"    Resolved {len(module_map)} imported module(s)")

    # Process module declarations (Phase 4)
    # module_decls can be external (module foo) or inline (module foo { ... })
    inline_modules = {}  # name -> Program (for inline modules)
    for mod_decl in getattr(entry_ast, 'module_decls', []):
        if mod_decl.is_inline:
            # Inline module - store body for later processing
            inline_modules[mod_decl.name] = mod_decl.body
            if verbose:
                print(f"    Inline module: {mod_decl.name}")
        else:
            # External module declaration - load from file
            # Look for name.saw or name/module.saw in the source directory
            mod_path = (mod_decl.name,)

            if mod_path not in resolved_modules:
                # Look in source directory for the module file
                source_dir = os.path.dirname(os.path.abspath(source_path))
                mod_file = os.path.join(source_dir, f"{mod_decl.name}.saw")
                mod_dir_file = os.path.join(source_dir, mod_decl.name, "module.saw")

                if os.path.isfile(mod_file):
                    with open(mod_file, 'r') as f:
                        mod_source = f.read()
                    mod_ast = parse_source(mod_source, mod_file, verbose)
                    module_map[mod_path] = mod_ast
                    resolved_modules.add(mod_path)
                    if verbose:
                        print(f"    Module: {mod_decl.name} -> {mod_file}")

                    # Also process any imports from this module
                    for sub_imp in getattr(mod_ast, 'imports', []):
                        pending_imports.append(sub_imp)
                elif os.path.isfile(mod_dir_file):
                    with open(mod_dir_file, 'r') as f:
                        mod_source = f.read()
                    mod_ast = parse_source(mod_source, mod_dir_file, verbose)
                    module_map[mod_path] = mod_ast
                    resolved_modules.add(mod_path)
                    if verbose:
                        print(f"    Module: {mod_decl.name} -> {mod_dir_file}")

                    # Also process any imports from this module
                    for sub_imp in getattr(mod_ast, 'imports', []):
                        pending_imports.append(sub_imp)
                else:
                    print(f"\033[1;31merror\033[0m: module `{mod_decl.name}` not found at {mod_file} or {mod_dir_file}", file=sys.stderr)
                    sys.exit(1)

    # Load builtins and build the (type-checked) builtin namespace once.
    # design 168 unit 4: `builtins` is a pristine pair the caller already has —
    # restored from the std cache, or built by the caller ahead of the entry
    # parse. A RE-ENTRY never takes it: place lowering rewrites std bodies in
    # place and the coroutine transform re-enters after that, so those passes
    # must re-check the program's own mutated std, not a fresh copy.
    if builtins is not None:
        builtin_ast, builtin_ns = builtins
    else:
        builtin_ast, builtin_ns = build_builtin_namespace(
            verbose, freestanding, runtime_build,
            builtin_ast=parsed['builtin_ast'] if parsed else None,
            target_triple=target_triple)
    # The AST to hand a re-entry is this one, BEFORE `_filter_std_ast` narrows
    # it for codegen: the filter drops the std files this program does not
    # compile in, and a re-entry has to start from the whole stdlib again.
    reentry_builtin_ast = builtin_ast

    # Helper to recursively collect all inline module bodies from an AST
    def collect_inline_module_bodies(ast):
        """Recursively collect all inline module bodies from an AST."""
        bodies = []
        for mod_decl in getattr(ast, 'module_decls', []):
            if mod_decl.is_inline and mod_decl.body:
                bodies.append(mod_decl.body)
                # Recursively collect from nested inline modules
                bodies.extend(collect_inline_module_bodies(mod_decl.body))
        return bodies

    # design 82 Part B: exclude non-imported import-required std modules from
    # codegen (and from the merged-namespace collision check). They stay
    # compiler-known for typechecking, but are not compiled into a program that
    # does not use them — so a user type named e.g. `IoError`/`File` never
    # collides with the (uncompiled) std one.
    import_asts = [entry_ast] + list(module_map.values())
    excluded_std_leaves, excluded_std_symbols = compute_std_codegen_exclusions(
        builtin_ns, import_asts)
    if excluded_std_leaves:
        builtin_ast = _filter_std_ast(builtin_ast, excluded_std_leaves)

    # Build merged AST for code generation (still needed for codegen)
    # Start with builtins
    merged_ast = builtin_ast

    # Merge ALL imported modules (needed for codegen - symbols must exist)
    for mod_ast in module_map.values():
        merged_ast = merge_programs(merged_ast, mod_ast)
        # Also merge inline module bodies from imported modules
        for inline_body in collect_inline_module_bodies(mod_ast):
            merged_ast = merge_programs(merged_ast, inline_body)

    # Merge inline modules from entry file (their symbols need to exist for codegen)
    for mod_name, mod_body in inline_modules.items():
        merged_ast = merge_programs(merged_ast, mod_body)
        # Also recursively merge any nested inline modules
        for inline_body in collect_inline_module_bodies(mod_body):
            merged_ast = merge_programs(merged_ast, inline_body)

    # Add entry module
    merged_ast = merge_programs(merged_ast, entry_ast)

    if verbose:
        print(f"    Merged {len(merged_ast.functions)} functions total")

    # =========================================================================
    # Phase 5.0: Per-Module Type Checking
    # =========================================================================
    # Type-check each module separately with its own namespace, then merge
    # namespaces for codegen. This ensures proper import scoping.

    if verbose:
        print("  Type checking (per-module)...")

    reporter = ErrorReporter(entry_source, source_path)
    # Add imported module sources for proper error context
    for mod_path, mod_source in module_sources.items():
        reporter.add_source(mod_path, mod_source)
    typechecker = TypeChecker(reporter, freestanding=freestanding,
                              runtime_build=runtime_build,
                              post_transform=post_transform,
                              no_hidden_alloc=no_hidden_alloc,
                              target_triple=target_triple,
                              target_features=target_features,
                              runtime_provider=runtime_provider)
    # design 84: carry the pre-computed suspending std (struct, method) set (std is
    # checked under a separate builtin typechecker, so the main one cannot infer it)
    # so the coroutine transform can embed nested suspending std methods.
    typechecker._std_suspending_methods = getattr(
        builtin_ns, '_std_suspending_methods', set())
    # design 82 Part B: the (std symbol name -> owning std file) map, so a bare
    # reference to a non-prelude std symbol errors with a "did you mean import"
    # hint instead of resolving silently.
    typechecker._std_symbol_file = getattr(builtin_ns, '_std_symbol_file', {})

    # The builtin namespace was built once by build_builtin_namespace(); all its
    # symbols are already type-checked and marked directly accessible.

    # Topologically sort modules by dependencies
    ordered_modules = topological_sort_modules(module_map)

    if verbose:
        print(f"    Type-checking {len(ordered_modules)} module(s) in dependency order")

    # Type-check each module in dependency order
    # checked_modules: module_path -> (ast, namespace)
    checked_modules = {}

    for mod_path in ordered_modules:
        mod_ast = module_map[mod_path]
        if verbose:
            print(f"      Checking module: {'.'.join(mod_path)}")

        mod_ns = typechecker.check_module(
            mod_ast,
            mod_path,
            checked_modules,
            builtin_ns,
            parent_namespace=None,
            is_entry=False
        )

        if mod_ns is None:
            reporter.print_all()
            sys.exit(1)

        checked_modules[mod_path] = (mod_ast, mod_ns)

    # Type-check external module declarations
    for mod_decl in getattr(entry_ast, 'module_decls', []):
        if not mod_decl.is_inline:
            mod_path = (mod_decl.name,)
            if mod_path in module_map and mod_path not in checked_modules:
                mod_ast = module_map[mod_path]
                if verbose:
                    print(f"      Checking module: {mod_decl.name}")

                mod_ns = typechecker.check_module(
                    mod_ast,
                    mod_path,
                    checked_modules,
                    builtin_ns,
                    parent_namespace=None,
                    is_entry=False
                )

                if mod_ns is None:
                    reporter.print_all()
                    sys.exit(1)

                checked_modules[mod_path] = (mod_ast, mod_ns)

    # Type-check the entry module
    if verbose:
        print("      Checking entry module")

    entry_ns = typechecker.check_module(
        entry_ast,
        (),  # Entry module has empty path
        checked_modules,
        builtin_ns,
        parent_namespace=None,
        is_entry=not object_only  # Only require main() for executables
    )

    if entry_ns is None:
        reporter.print_all()
        sys.exit(1)

    # design 150: warnings never affect the exit code, so the success path is
    # the ONLY place most of them are ever seen — `print_all` runs on failure.
    reporter.print_warnings()

    # design 113b: enforce the runtime-build sync-only discipline. Every seam is
    # an `@export` function, which the design-22 effect system already treats as
    # a sync context (an `@export`ed body has no Saw caller to drive it across a
    # coroutine boundary), so a suspending seam body — a `yield_now`, a blocking
    # extern, `__saw_io_park`, a TaskGroup/channel op — is reported as a clean sync
    # violation. The entry module was checked with is_entry=False (object_only
    # suppresses the main() requirement), so the whole-program effect fixpoint
    # has not run yet — run it now, then surface any violation.
    # design 122 unit E: `--emit-docs` needs the same fixpoint. The entry module
    # is checked with is_entry=False under `object_only`, so nothing ran the
    # whole-program effect analysis — every node's `suspends` bit was still
    # False, and the docs emitter reported `"effect": "sync"` for every
    # suspending USER function (only a hardcoded std name list said otherwise).
    if runtime_build or docs_out is not None:
        typechecker.finalize_effects()
        if reporter.has_errors():
            reporter.print_all()
            sys.exit(1)

    if verbose:
        print("    Type check passed")

    # Merge all namespaces for codegen
    # Start with builtin namespace, then merge all module namespaces
    from namespace import Namespace
    merged_ns = Namespace()
    collisions = []
    merged_ns.merge_into(builtin_ns, source_label="<builtins>", collisions=collisions,
                         exclude=excluded_std_symbols)

    for mod_path, (mod_ast, mod_ns) in checked_modules.items():
        label = '.'.join(mod_path) if mod_path else "<entry>"
        merged_ns.merge_into(mod_ns, source_label=label, collisions=collisions)

    merged_ns.merge_into(entry_ns, source_label="<entry>", collisions=collisions)

    # Design 26 item 1: a symbol name bound to two distinct definitions across
    # merged module namespaces is an unresolvable ambiguity (two modules export
    # the same name; the importer's bare use cannot pick one). Report it at
    # check time instead of letting codegen crash with a DuplicatedNameError.
    if collisions:
        for category, name, src1, src2 in collisions:
            reporter.error(
                ErrorKind.DUPLICATE_FUNCTION,
                f"ambiguous {category} `{name}`: defined in both `{src1}` and `{src2}`",
                1, 1,
                hint=f"rename one definition, or import `{name}` from a single module"
            )
        reporter.print_all()
        sys.exit(1)

    # design 121 `--emit-docs`: the program is type-checked, which is all
    # documentation needs. Hand the caller the checked ASTs plus the namespaces
    # and stop here — before the coroutine transform, so the documented AST is
    # the one the author wrote rather than its frame-struct rewrite.
    if docs_out is not None:
        docs_out.update({
            'entry_ast': entry_ast,
            'entry_path': source_path,
            'module_map': module_map,
            'builtin_ast': builtin_ast,
            'builtin_ns': builtin_ns,
            'namespace': merged_ns,
            'typechecker': typechecker,
        })
        return None, merged_ast

    # design 141/146: the use-site half of element places. A place use needs the
    # receiver's TYPE to become a window call (`__window`'s parameter type is
    # where `&var T` comes from), so it runs here — after checking, before the
    # coroutine transform, whose own rewrite would otherwise have to understand
    # places. It rewrites std and every imported module as well as the entry
    # file, which is exactly what the re-entry's AST reuse above makes possible.
    if not places_lowered:
        from place_uses import transform_place_uses
        place_asts = [reentry_builtin_ast] + list(module_map.values()) + [entry_ast]
        if transform_place_uses(place_asts, merged_ns, reporter):
            if reporter.has_errors():
                reporter.print_all()
                sys.exit(1)
            if verbose:
                print("  Lowered place uses; re-checking...")
            return _prepare_codegen(source_path, entry_ast, entry_source, verbose,
                                    object_only, target_triple, freestanding,
                                    module_paths, runtime_build,
                                    post_transform=post_transform,
                                    target_features=target_features,
                                    parsed={'module_map': module_map,
                                            'module_sources': module_sources,
                                            'builtin_ast': reentry_builtin_ast},
                                    places_lowered=True,
                                    no_hidden_alloc=no_hidden_alloc,
                                    runtime_provider=runtime_provider)
        if reporter.has_errors():
            reporter.print_all()
            sys.exit(1)

    # design 44: the source-level coroutine transform. If the program drove any
    # suspending function (`__saw_drive(...)` recorded roots during the effect
    # analysis above), rewrite those roots into frame structs + resume methods on
    # the entry AST and re-run this front half. The rewrite deletes the `__saw_drive`
    # sites, so the recursive pass finds NO driven roots and proceeds straight to
    # codegen — a natural base case. Non-driven programs never enter this branch,
    # so the transform is OFF by construction and their path is unchanged.
    driven = (getattr(typechecker, "_driven_roots", None)
              or getattr(typechecker, "_driven_method_roots", None)
              or getattr(typechecker, "_spawn_roots", None)
              or getattr(typechecker, "_main_suspends", False))
    if driven:
        from coro_transform import transform_program, CoroTransformError
        try:
            changed = transform_program(entry_ast, typechecker,
                                        imported_ast=merged_ast)
        except CoroTransformError as e:
            # design 74 (A8): anchor the coroutine-transform rejection at the
            # user's source line (file:line:col + snippet) via the shared error
            # reporter, exactly like a type error — never a bare message.
            if getattr(e, "line", 0):
                reporter.error(
                    ErrorKind.TYPE_MISMATCH, e.message, e.line,
                    e.column or 1, source_file=e.source_file)
                reporter.print_all()
            else:
                # No line to anchor to, so this bypasses the reporter — and
                # with it the design-144 qualifier scrub every other diagnostic
                # gets. Apply it here rather than let one message render
                # `Header$m$dep` at the user.
                print(f"\033[1;31merror\033[0m: "
                      f"{ErrorReporter.humanize(e.message)}", file=sys.stderr)
            sys.exit(1)
        if changed:
            if verbose:
                print("  Applied coroutine transform; re-checking...")
            return _prepare_codegen(source_path, entry_ast, entry_source, verbose,
                                    object_only, target_triple, freestanding,
                                    module_paths, runtime_build,
                                    post_transform=True,
                                    target_features=target_features,
                                    parsed={'module_map': module_map,
                                            'module_sources': module_sources,
                                            'builtin_ast': reentry_builtin_ast},
                                    places_lowered=True,
                                    no_hidden_alloc=no_hidden_alloc,
                                    runtime_provider=runtime_provider)

    # Set this as the typechecker's namespace for compatibility
    typechecker.namespace = merged_ns

    if verbose:
        print("  Building code generator...")
    # design 168 unit 2: emit only what the entry graph reaches. Sound exactly
    # when this compile owns the whole program — an executable link, or an object
    # that already internalizes everything but its `@export`s (freestanding,
    # --runtime-build). A plain hosted `-c` object is somebody else's to link, so
    # it keeps every symbol.
    whole_program = (not object_only) or freestanding or runtime_build

    codegen = CodeGenerator(typechecker.namespace, target_triple=target_triple,
                            freestanding=freestanding, source_path=source_path,
                            runtime_build=runtime_build,
                            target_features=target_features,
                            strip_unreachable=whole_program)
    return codegen, merged_ast


def _emit_object(codegen, source_path: str, output_path: str, verbose: bool,
                 object_only: bool, optimize: bool, freestanding: bool = False,
                 runtime_provider: bool = False):
    """Write the module's IR sidecar, compile to an object file, and (for
    executables) link it. Shared output tail for the compile pipeline."""
    llvm_ir = codegen.emit_ir(optimize=False)

    # Write LLVM IR to a sidecar file (for debugging)
    ir_path = output_path + ".ll"
    with open(ir_path, 'w') as f:
        f.write(llvm_ir)
    if verbose:
        print(f"  Wrote IR to {ir_path}")

    if verbose:
        print("  Compiling to object code...")

    if object_only:
        # Output directly to the specified path (should end in .o)
        obj_path = output_path if output_path.endswith('.o') else output_path + '.o'
        codegen.compile_to_object(obj_path, optimize=optimize)

        if verbose:
            print(f"  Output: {obj_path}")
        print(f"Compiled {source_path} -> {obj_path}")
    else:
        # Compile to temp object file, then link
        obj_path = output_path + ".o"
        codegen.compile_to_object(obj_path, optimize=optimize)

        # Link with system linker (clang handles libc linking automatically).
        # design 113b: a hosted executable also links the per-host Saw runtime
        # (the __saw_rt_* seam bodies), built + cached under `.build/rt/`.
        if verbose:
            print("  Linking...")

        rt_objects = []
        if runtime_provider:
            # design 149 unit c: this package IS the runtime. Linking ours beside
            # it would define every seam twice; the whole point of declaring the
            # role is to take the job over.
            if verbose:
                print("  Runtime objects: none (this package provides the seams)")
        else:
            try:
                from rt_build import build_runtime, RuntimeBuildError
                rt_objects = build_runtime(codegen.triple, verbose=verbose)
            except RuntimeBuildError as e:
                print(f"\033[1;31merror\033[0m: the Saw runtime failed to build "
                      f"(needed to link a hosted binary):\n{e}", file=sys.stderr)
                sys.exit(1)

        if verbose and rt_objects:
            print("  Runtime objects:")
            for o in rt_objects:
                print(f"    {o}")

        # design 168 unit 1 (DF-164b): dead-strip the link. Codegen emits every
        # loaded std definition with external linkage, so -O1's globaldce cannot
        # touch any of it and 52-76% of every Saw binary was unreachable stdlib
        # (`hello` measured 218,216 bytes, 155 KB of it dead). The linker is the
        # one component that sees the whole program, so it is where the floor
        # gets set — and it stays the backstop for the pre-LLVM reachability
        # strip, whose soundness rule is "when in doubt, keep it".
        #
        # `@export`ed symbols survive: `_emit_llvm_used` (design 58) puts them in
        # `@llvm.used`, which LLVM lowers to `.no_dead_strip` on mach-O and to an
        # SHF_GNU_RETAIN/`llvm.used` keep on ELF. `main` is the entry point and is
        # a root by definition.
        apple = codegen._is_apple_triple()
        strip_flag = "-Wl,-dead_strip" if apple else "-Wl,--gc-sections"

        # Say the keep-roots to the LINKER as well, rather than trusting each
        # platform's lowering of `@llvm.used`. On mach-O that lowering is
        # verifiable here and works — an `@export`ed function nothing calls is
        # still in the binary. On ELF it rests on the backend marking the section
        # retained, which cannot be checked from this host. `-u` is the portable
        # spelling of "this symbol is required" and both linkers honour it, so an
        # export is a keep-root by instruction rather than by inference. mach-O
        # prefixes C symbols with an underscore.
        keep_flags = [f"-Wl,-u,{'_' if apple else ''}{g.name}"
                      for g in codegen._exported_llvm_globals]

        link_cmd = ["clang", obj_path, *rt_objects, strip_flag, *keep_flags,
                    "-o", output_path]

        try:
            result = subprocess.run(link_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Linking failed: {result.stderr}", file=sys.stderr)
                sys.exit(1)
        except FileNotFoundError:
            print("Error: clang not found. Please install LLVM/clang.", file=sys.stderr)
            sys.exit(1)

        # On macOS the executable does not CONTAIN the DWARF — it carries a
        # debug map (N_OSO stabs) pointing back at this object file, so
        # deleting it strips every Saw line table lldb can resolve (design 69
        # emitted them for nothing). Keep the object beside the output there.
        # ELF links the DWARF into the binary, so elsewhere it is scratch.
        if sys.platform != "darwin":
            os.remove(obj_path)

        if verbose:
            print(f"  Output: {output_path}")

        print(f"Compiled {source_path} -> {output_path}")


def compile_saw(source_path: str, output_path: str, verbose: bool = False, object_only: bool = False, optimize: bool = True, target_triple: str = None, freestanding: bool = False, module_paths: dict = None, runtime_build: bool = False, target_features: str = None, no_hidden_alloc: bool = False, runtime_provider: bool = False):
    """Compile a Saw source file to an executable or object file.

    A single file is just a module graph of size one, so there is one pipeline:
    parse the entry file, run `_prepare_codegen` (module resolution + builtins +
    type checking), then generate and emit. `_prepare_codegen` handles the
    no-import case (empty module map) identically to a multi-module program.

    Args:
        source_path: Path to the .saw source file
        output_path: Path for output (executable or .o file)
        verbose: Print verbose progress messages
        object_only: If True, compile to .o without linking (no main() required)
        optimize: If True (default), run the O1 optimization pipeline; -O0 disables it
        target_triple: Optional LLVM target triple for cross-compilation (default host)
        freestanding: If True, emit for the freestanding profile (seams as
            declarations only, hosted std modules excluded, unlinked object output)
        no_hidden_alloc: If True, reject the allocations the compiler inserts
            that no source construct names (design 135)
    """
    # Freestanding and runtime-build both emit an unlinked object file; the
    # user (or the runtime-build cache machinery) owns linking.
    if freestanding or runtime_build:
        object_only = True

    # Read source file
    with open(source_path, 'r') as f:
        source = f.read()

    if verbose:
        print(f"Compiling {source_path}...")

    # design 168 unit 4: the stdlib is parsed + type-checked BEFORE the entry
    # file, always — cached or not. Two reasons, and only one of them is speed.
    #
    # The cache needs it: `pickle` preserves `node_id` verbatim, so a blob
    # restored AFTER the entry parse carries ids the entry file already took, and
    # a collision silently merges two functions' suspend analysis (design 164's
    # prototype miscompiled 13 of 1,114 examples exactly that way).
    #
    # But building it first on the COLD path too is what makes the cache
    # invisible: both paths then allocate node ids in the same order, so a warm
    # compile is not merely correct but byte-identical to a cold one. Restoring
    # ahead of a cold build that still ran late would have left every generated
    # name shifted between the two, which is what turned design 164's strict
    # differential red.
    builtins = _prepared_builtins(verbose, freestanding, runtime_build,
                                  target_triple, target_features,
                                  no_hidden_alloc, optimize)

    if verbose:
        print("  Parsing...")
    entry_ast = parse_source(source, source_path, verbose)
    entry_ast.source_path = os.path.abspath(source_path)

    if verbose and uses_modules(entry_ast):
        print("  Module system detected:")
        for imp in entry_ast.imports:
            print(f"    import {'.'.join(imp.path)}")
        for mod in entry_ast.module_decls:
            print(f"    module {mod.name}")

    codegen, merged_ast = _prepare_codegen(
        source_path, entry_ast, source, verbose, object_only, target_triple,
        freestanding, module_paths, runtime_build,
        target_features=target_features, no_hidden_alloc=no_hidden_alloc,
        runtime_provider=runtime_provider, builtins=builtins)

    if verbose:
        print("  Generating LLVM IR...")
    run_codegen(codegen, merged_ast)
    if verbose:
        print("  Generated LLVM IR")

    _emit_object(codegen, source_path, output_path, verbose, object_only,
                 optimize, freestanding=freestanding,
                 runtime_provider=runtime_provider)


def emit_docs(source_path: str, output_path: str = None, verbose: bool = False,
              include_private: bool = False, module_paths: dict = None):
    """Type-check `source_path` and write its documentation JSON (design 121).

    The entry file is also the selector: its module and every module it imports
    — including `import std.<module>` — are documented, so a doc driver is a file
    that imports what it wants covered. Output goes to `output_path`, or stdout.
    """
    from docs_emit import build_docs, render_docs

    with open(source_path, 'r') as f:
        source = f.read()

    if verbose:
        print(f"Documenting {source_path}...")
    entry_ast = parse_source(source, source_path, verbose)
    entry_ast.source_path = os.path.abspath(source_path)

    ctx = {}
    _prepare_codegen(source_path, entry_ast, source, verbose, object_only=True,
                     module_paths=module_paths, docs_out=ctx)
    text = render_docs(build_docs(ctx, include_private=include_private))

    if output_path:
        with open(output_path, 'w') as f:
            f.write(text)
        if verbose:
            print(f"  Wrote {output_path}")
    else:
        sys.stdout.write(text)


def main():
    parser = argparse.ArgumentParser(
        description="Saw Language Compiler",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    sawc hello.saw              Compile hello.saw to .build/hello
    sawc hello.saw -o myprogram Compile to ./myprogram
    sawc hello.saw -v           Verbose output
        """
    )

    parser.add_argument("input", help="Input .saw file")
    parser.add_argument("-o", "--output",
                        help="Output executable name (default: .build/<source>)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("-c", action="store_true", help="Compile to object file (.o) without linking, no main() required")
    parser.add_argument("--emit-ir", action="store_true", help="Only emit LLVM IR, don't compile")
    parser.add_argument("--emit-ast", action="store_true", help="Dump typed AST for debugging")
    parser.add_argument("--ids", action="store_true",
                        help="With --emit-ast: include each node's stable node_id. "
                             "Off by default -- ids are stable within a run but "
                             "carry no cross-implementation meaning, so the "
                             "canonical dump (the parser-port oracle) omits them.")
    parser.add_argument("--emit-docs", action="store_true", dest="emit_docs",
                        help="Type-check and emit documentation JSON instead of "
                             "code (design 121). Covers the entry module and every "
                             "module it imports, std included. Writes to -o, else "
                             "stdout.")
    parser.add_argument("--emit-docs-all", action="store_true", dest="emit_docs_all",
                        help="Like --emit-docs, but keep private fields, methods "
                             "and inits (internal tooling).")
    parser.add_argument("--emit-frame-layout", action="store_true",
                        dest="emit_frame_layout",
                        help="Emit the coroutine FRAME LAYOUT report as JSON "
                             "instead of code (design 163): per monomorphized "
                             "`__Frame_*`, its total size and alignment, every "
                             "field's offset and size, and for each embedded "
                             "callee sub-frame the callee it holds and the "
                             "resume state in which it is live. Writes to -o, "
                             "else stdout. Analysis only.")
    parser.add_argument("-O0", dest="no_optimize", action="store_true",
                        help="Disable optimization passes (emit raw codegen output for debugging)")
    parser.add_argument("--target", metavar="TRIPLE",
                        help="Target triple for cross-compilation (default: host)")
    parser.add_argument("--target-features", metavar="FEATURES",
                        dest="target_features",
                        help="LLVM subtarget features for --target, comma separated "
                             "(e.g. `+m,+a,+c` for rv32imac). A triple names an "
                             "architecture but not its optional extensions; base "
                             "rv32i has no divide instruction, so an integer `/` "
                             "becomes a libcall the freestanding profile cannot link")
    parser.add_argument("--freestanding", action="store_true",
                        help="Freestanding profile: runtime seams as declarations only, "
                             "no hosted std modules (file/process/env/directory), "
                             "no Float printing, unlinked object output")
    parser.add_argument("--no-hidden-alloc", action="store_true",
                        dest="no_hidden_alloc",
                        help="Reject allocations the compiler inserts that no "
                             "source construct names (design 135): string "
                             "interpolation, an escaping closure's captured "
                             "environment, and `print` of a user Printable. "
                             "Allocations the source names — a `Vector.push`, a "
                             "collection literal, `spawn`, a written "
                             "`Box<any Error>` — are unaffected. Orthogonal to "
                             "--freestanding, and recommended alongside it.")
    parser.add_argument("--runtime-build", action="store_true", dest="runtime_build",
                        help="Runtime-build mode (design 113b): compile a Saw runtime "
                             "that `@export`s the frozen `__saw_rt_*` ABI. Sync-only, "
                             "suppresses seam auto-declaration for exported seams, "
                             "unlinked object output. Used to build sawc/rt/.")
    parser.add_argument("--runtime-provider", action="store_true",
                        dest="runtime_provider",
                        help="This package IS a runtime (design 149; Blade passes "
                             "it for `[package] runtime = true`). Permits "
                             "`@export`ing the frozen `__saw_rt_*` seams, CHECKS "
                             "each exported seam's signature against "
                             "sawc/rt/ABI.md, and links no runtime of ours beside "
                             "it. Unlike --runtime-build this is an ordinary "
                             "package build: std is available and the output links.")
    parser.add_argument("--module-path", metavar="NAME=DIR", action="append",
                        default=[], dest="module_path",
                        help="Map package NAME to source directory DIR "
                             "(`import NAME` -> DIR/lib.saw, `import NAME.sub` -> "
                             "DIR/sub.saw). Repeatable. Used by the package manager.")
    parser.add_argument("-W", metavar="NAME", action="append",
                        default=[], dest="warnings",
                        help="Enable a warning category (design 150). Repeatable; "
                             "`-W all` enables every one. Warnings are off by "
                             "default and never affect the exit code. "
                             "Categories: "
                             + ", ".join(sorted(WARNING_CATEGORIES)))

    args = parser.parse_args()

    # design 150: warning categories are opt-in, and an unrecognized one is a
    # clean error rather than a silently ignored flag — a misspelled `-W` that
    # quietly did nothing would read as "the code is clean".
    unknown_warnings = enable_warnings(args.warnings)
    if unknown_warnings:
        for name in unknown_warnings:
            print(f"\033[1;31merror\033[0m: unknown warning category `{name}`",
                  file=sys.stderr)
        print("known categories: " + ", ".join(sorted(WARNING_CATEGORIES)),
              file=sys.stderr)
        sys.exit(1)

    # Parse --module-path NAME=DIR pairs into a name->dir dict.
    module_paths = {}
    for entry in args.module_path:
        if '=' not in entry:
            print(f"\033[1;31merror\033[0m: --module-path expects NAME=DIR, got "
                  f"`{entry}`", file=sys.stderr)
            sys.exit(1)
        name, _, dir_part = entry.partition('=')
        name = name.strip()
        dir_part = dir_part.strip()
        if not name or not dir_part:
            print(f"\033[1;31merror\033[0m: --module-path expects NAME=DIR, got "
                  f"`{entry}`", file=sys.stderr)
            sys.exit(1)
        module_paths[name] = dir_part

    if not os.path.exists(args.input):
        print(f"Error: File not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    # design 121: documentation extraction replaces code generation entirely, and
    # writes to stdout when no -o is given (so it composes in a shell pipeline).
    if args.emit_docs or args.emit_docs_all:
        emit_docs(args.input, args.output, args.verbose,
                  include_private=args.emit_docs_all, module_paths=module_paths)
        return

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        # Use input filename without extension, place in .build/ directory
        basename = os.path.basename(args.input)
        name_without_ext = os.path.splitext(basename)[0]

        # Ensure .build/ directory exists
        build_dir = ".build"
        os.makedirs(build_dir, exist_ok=True)

        output_path = os.path.join(build_dir, name_without_ext)

    if args.emit_ast:
        # Dump typed AST
        from ast_dump import dump_ast

        with open(args.input, 'r') as f:
            source = f.read()

        # Load builtins
        builtin_ast = load_builtins(args.verbose)

        try:
            lexer = Lexer(source)
            tokens = lexer.tokenize()
            parser_obj = Parser(tokens, doc_comments=lexer.doc_comments)
            user_ast = parser_obj.parse()
        except SyntaxError as e:
            print(f"\033[1;31merror\033[0m: {e}", file=sys.stderr)
            sys.exit(1)

        # Merge builtins with user program
        ast = merge_programs(builtin_ast, user_ast)

        # Type check (this annotates None types, etc.)
        reporter = ErrorReporter(source, args.input)
        typechecker = TypeChecker(reporter)
        if not typechecker.check(ast):
            reporter.print_all()
            sys.exit(1)

        # Dump AST
        ast_output = dump_ast(ast, ids=args.ids)
        print(ast_output)

    elif args.emit_frame_layout:
        # design 163: the frame-layout report needs the SAME front half plus
        # codegen (LLVM is the layout authority), but nothing after it — no
        # object, no link. Same shape as --emit-ir below.
        from frame_layout import build_report, render_report

        with open(args.input, 'r') as f:
            source = f.read()

        entry_ast = parse_source(source, args.input, args.verbose)
        entry_ast.source_path = os.path.abspath(args.input)

        codegen, merged_ast = _prepare_codegen(
            args.input, entry_ast, source, verbose=args.verbose,
            object_only=True, target_triple=args.target,
            freestanding=args.freestanding, module_paths=module_paths,
            runtime_build=args.runtime_build,
            target_features=args.target_features,
            no_hidden_alloc=args.no_hidden_alloc,
            runtime_provider=args.runtime_provider)
        run_codegen(codegen, merged_ast)
        text = render_report(build_report(codegen, merged_ast, args.input))
        if args.output:
            with open(args.output, 'w') as f:
                f.write(text)
            if args.verbose:
                print(f"  Wrote {args.output}")
        else:
            sys.stdout.write(text)

    elif args.emit_ir:
        # Emit IR only, through the same front half as a real compile so that
        # builtins (String/Vector/Result) are loaded and module imports resolve.
        with open(args.input, 'r') as f:
            source = f.read()

        entry_ast = parse_source(source, args.input, args.verbose)
        entry_ast.source_path = os.path.abspath(args.input)

        codegen, merged_ast = _prepare_codegen(
            args.input, entry_ast, source, verbose=args.verbose,
            object_only=args.c, target_triple=args.target,
            freestanding=args.freestanding, module_paths=module_paths,
            runtime_build=args.runtime_build,
            target_features=args.target_features,
            no_hidden_alloc=args.no_hidden_alloc,
            runtime_provider=args.runtime_provider)
        run_codegen(codegen, merged_ast)
        llvm_ir = codegen.emit_ir(optimize=not args.no_optimize)

        ir_output = output_path + ".ll"
        with open(ir_output, 'w') as f:
            f.write(llvm_ir)
        print(f"Emitted IR to {ir_output}")
    else:
        # -c, --freestanding, and --runtime-build all emit an unlinked object
        # file; ensure the output path ends with .o so it is not mistaken for an
        # executable.
        if (args.c or args.freestanding or args.runtime_build) and not output_path.endswith('.o'):
            output_path = output_path + '.o'
        compile_saw(args.input, output_path, verbose=args.verbose,
                    object_only=args.c, optimize=not args.no_optimize,
                    target_triple=args.target, freestanding=args.freestanding,
                    module_paths=module_paths, runtime_build=args.runtime_build,
                    target_features=args.target_features,
                    no_hidden_alloc=args.no_hidden_alloc,
                    runtime_provider=args.runtime_provider)


if __name__ == "__main__":
    main()
