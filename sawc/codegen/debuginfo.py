"""DWARF debug-info emission (design 69, Part 1).

Line tables ONLY (no variable/type info): every emitted instruction in a user
function carries the source line of the Saw statement it lowers, so a debugger
(lldb/gdb) can set line breakpoints and print `file:line` backtraces — including
for panics, which abort through `saw_panic`.

Mechanism (llvmlite 0.48 debug metadata):
  - module flags "Debug Info Version"=3 + "Dwarf Version"=4
  - one DICompileUnit (registered in !llvm.dbg.cu) over the entry DIFile
  - one DIFile per distinct source path (multi-module correct)
  - one DISubprogram per user function/method, attached via `func.set_metadata`
  - a DILocation per (function, line) attached to instructions through the
    builder's `debug_metadata` attribute (set once per statement)

Re-entrancy: the active subprogram is looked up by the CURRENT builder's llvm
function name (`_di_func_subprograms`), never a single "current" field, so a
nested body generation (closure / monomorphization) can never bleed one
function's scope onto another's instructions. A function without a subprogram
(runtime seams, drop glue, closures) simply gets no `!dbg` — which the LLVM
verifier accepts (only functions that HAVE a subprogram must carry locations).
"""

import os
from llvmlite import ir


class DebugInfoMixin:
    def _di_init(self, source_path):
        """Initialize per-CodeGenerator debug-info state. `source_path` is the
        entry .saw file (the compilation's main file)."""
        self._di_enabled = True
        self._di_source_path = source_path
        self._di_cu = None
        self._di_subroutine_type = None
        self._di_files = {}                 # source path -> DIFile
        self._di_func_subprograms = {}      # llvm func name -> DISubprogram
        self._di_func_basename = {}         # llvm func name -> source basename
        self._di_loc_cache = {}             # (func name, line, col) -> DILocation

    def _di_setup_module(self):
        """Emit module-level debug metadata (flags + compile unit). Called once,
        after the module exists and before any function body is generated."""
        if not getattr(self, "_di_enabled", False):
            return
        i32 = ir.IntType(32)
        self.module.add_named_metadata(
            "llvm.module.flags",
            [ir.Constant(i32, 2), "Debug Info Version", ir.Constant(i32, 3)])
        self.module.add_named_metadata(
            "llvm.module.flags",
            [ir.Constant(i32, 2), "Dwarf Version", ir.Constant(i32, 4)])

        main_file = self._di_file(self._di_source_path)
        self._di_cu = self.module.add_debug_info("DICompileUnit", {
            "language": ir.DIToken("DW_LANG_C99"),
            "file": main_file,
            "producer": "sawc (Saw compiler)",
            "isOptimized": True,   # the default pipeline is O1
            "runtimeVersion": 0,
            "emissionKind": ir.DIToken("FullDebug"),
        }, is_distinct=True)
        self.module.add_named_metadata("llvm.dbg.cu", self._di_cu)
        # A shared, minimal subroutine type (no parameter/return type info — line
        # tables don't need it). `types: !{null}` = unspecified void signature.
        self._di_subroutine_type = self.module.add_debug_info(
            "DISubroutineType", {"types": self.module.add_metadata([None])})

    def _di_file(self, path):
        """DIFile for a source path (cached). Empty/unknown paths fall back to
        the entry file so synthesized declarations still resolve."""
        if not path:
            path = self._di_source_path or "<unknown>.saw"
        cached = self._di_files.get(path)
        if cached is not None:
            return cached
        abspath = os.path.abspath(path)
        f = self.module.add_debug_info("DIFile", {
            "filename": os.path.basename(abspath),
            "directory": os.path.dirname(abspath),
        })
        self._di_files[path] = f
        return f

    def _di_begin_function(self, llvm_func, name, source_file, line):
        """Attach a DISubprogram to `llvm_func` and prime the builder location.

        Idempotent-safe per llvm function (each is generated once). Sets the
        builder's initial debug location to `line or 1` so EVERY instruction —
        including a fully synthesized method's, whose statements may carry line 0
        — gets a valid `!dbg` (required once the function has a subprogram)."""
        if not getattr(self, "_di_enabled", False):
            return
        di_file = self._di_file(source_file)
        sp = self.module.add_debug_info("DISubprogram", {
            "name": name,
            "linkageName": llvm_func.name,
            "file": di_file,
            "line": line or 1,
            "type": self._di_subroutine_type,
            "scopeLine": line or 1,
            "unit": self._di_cu,
            "isDefinition": True,
            "isOptimized": True,
        }, is_distinct=True)
        llvm_func.set_metadata("dbg", sp)
        self._di_func_subprograms[llvm_func.name] = sp
        self._di_func_basename[llvm_func.name] = os.path.basename(
            os.path.abspath(source_file)) if source_file else \
            os.path.basename(os.path.abspath(self._di_source_path)) \
            if self._di_source_path else "<unknown>.saw"
        self._di_set_line(line or 1)

    def _di_set_line(self, line, column=0):
        """Point the builder at `line`, scoped to the current function's
        subprogram. A non-positive line is ignored (the previous location is
        inherited) — this is what keeps synthesized line-0 nodes from opening
        `!DILocation(line: 0)` gaps in the table."""
        if not getattr(self, "_di_enabled", False):
            return
        if self.builder is None:
            return
        fname = self.builder.function.name
        sp = self._di_func_subprograms.get(fname)
        if sp is None:
            return
        if not line or line <= 0:
            return
        key = (fname, line, column)
        loc = self._di_loc_cache.get(key)
        if loc is None:
            loc = self.module.add_debug_info("DILocation", {
                "line": line, "column": column, "scope": sp})
            self._di_loc_cache[key] = loc
        self.builder.debug_metadata = loc

    def _di_current_basename(self):
        """Source basename of the function currently being generated (for panic
        message text). Falls back to the entry file's basename."""
        if not getattr(self, "_di_enabled", False):
            return None
        if self.builder is None:
            return None
        base = self._di_func_basename.get(self.builder.function.name)
        if base:
            return base
        if self._di_source_path:
            return os.path.basename(os.path.abspath(self._di_source_path))
        return None
