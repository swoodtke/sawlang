#!/usr/bin/env python3
"""A nested body must hand back every kind of per-function codegen state (SL-356).

Codegen keeps the function it is emitting in generator attributes — the bindings
in scope, their types, the cleanup scopes, the statement's temporaries, the
enclosing catch, the return type. A closure body is a SECOND function emitted in
the middle of the first, so it blanks that state, fills it with its own, and
puts the enclosing function's back. The pair was two hand-maintained lists, and
a kind of state that reached the blank side and missed the restore side left
the enclosing function without its zero-sized bindings; a kind that reached
neither side let a closure append its temporaries to the enclosing statement's
list and branch to the enclosing function's catch block.

One table is now the whole answer — `FunctionCodegenState.FIELDS` in
`sawc/codegen/closures.py` — and this lane is what keeps it the whole answer:

  1. the record is DRIVEN by that table (capture/blank/restore iterate it and
     name no attribute of their own), so a field cannot be half-wired;
  2. no nested-body site keeps a private `saved_x = self.x` beside it;
  3. EVERY attribute a generator method assigns is classified exactly once:
     in the table, in `SHARED_WITH_NESTED_BODIES` with the reason it is safe
     to share, or in this lane's `MODULE_STATE` as state that outlives a
     function. What a named function's PROLOGUE initializes, and what ANY
     codegen method saves and restores or pushes and pops around an extent of
     generation (a statement, a try body, a loop, an instantiation), may not
     be called module state — the prologue set alone is not the whole
     inventory;
  4. every name in the tables is real state the generator holds, and no
     shared entry outlives the code it describes;
  5. and — the check that a structural claim cannot make — a name taken off
     the restore (the half-wired shape) or off both halves (the unlisted
     shape), or an identity entry captured by copy, must break a real compile
     or its pin's output, each beside an uninjected control so the failure is
     the injection's and not the harness's.

Run from the repo root:  ./.venv/bin/python tools/test_closure_state.py
Exit code 0 = pass; nonzero (with a diagnostic per problem) = fail.
"""
import ast
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODEGEN = os.path.join(REPO, "sawc", "codegen")
CLOSURES = os.path.join(CODEGEN, "closures.py")
METHODS = os.path.join(CODEGEN, "methods.py")
SAWC_MAIN = os.path.join(REPO, "sawc", "sawc.py")

RECORD = "FunctionCodegenState"
DRIVEN_METHODS = ("capture", "blank", "restore")
# Every site that emits a nested body has to go through the record.
NESTED_BODY_SITES = ("_generate_closure", "_generate_env_dtor")
# A prologue is a named function's body generator; this is how one is spotted.
PROLOGUE_MARKER = "variables"
# The generator and its mixins — the classes whose `self.<x>` is codegen state.
GENERATOR_CLASS = "CodeGenerator"
MIXIN_SUFFIX = "Mixin"


def parse(path):
    with open(path) as fh:
        return ast.parse(fh.read(), filename=path)


def codegen_files():
    return sorted(os.path.join(CODEGEN, fn) for fn in os.listdir(CODEGEN)
                  if fn.endswith(".py"))


def find_class(tree, name):
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def find_def(scope, name):
    for node in ast.walk(scope):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def is_self_attr(node):
    return (isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name) and node.value.id == "self")


def generator_methods(tree):
    """(class name, method node) for every method of the generator or a mixin."""
    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef):
            continue
        if not (cls.name == GENERATOR_CLASS or cls.name.endswith(MIXIN_SUFFIX)):
            continue
        for fn in cls.body:
            if isinstance(fn, ast.FunctionDef):
                yield cls.name, fn


def self_assign_targets(fn):
    """`self.<x>` names assigned as direct statements of `fn`'s body."""
    names = []
    for stmt in fn.body:
        if not isinstance(stmt, ast.Assign):
            continue
        for target in stmt.targets:
            if is_self_attr(target):
                names.append(target.attr)
    return names


def saved_and_restored(fn):
    """`self.<x>` names `fn` reads into a local and later assigns that local back.

    That pair is how codegen scopes state to an extent of generation — a
    statement, a try body, a generic instantiation, a nested body — and every
    such kind is one a nested body either isolates or shares on purpose. A
    lazily built cache reads the attribute too, but rebinds the local to a
    fresh container before writing it back, so a local that is bound more
    than once is not a saved copy.
    """
    bindings = {}  # local name -> how many times the function binds it
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bindings[target.id] = bindings.get(target.id, 0) + 1
    saved = {}  # attribute -> the locals it was read into
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        attr = None
        if is_self_attr(value):
            attr = value.attr
        elif (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                and value.func.id == "getattr" and len(value.args) >= 2
                and isinstance(value.args[0], ast.Name)
                and value.args[0].id == "self"
                and isinstance(value.args[1], ast.Constant)):
            attr = value.args[1].value
        if attr is None:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and bindings.get(target.id) == 1:
                saved.setdefault(attr, set()).add(target.id)
    restored = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Name):
            continue
        for target in node.targets:
            if (is_self_attr(target)
                    and node.value.id in saved.get(target.attr, ())):
                restored.add(target.attr)
    return restored


def stack_scoped(fn):
    """`self.<x>` names `fn` both pushes onto and pops off.

    A push and its pop in one method bracket an extent of generation just as a
    save and its restore do; the stack is never reassigned, so the save/restore
    census alone does not see it.
    """
    pushed, popped = set(), set()
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and is_self_attr(node.func.value)):
            if node.func.attr == "append":
                pushed.add(node.func.value.attr)
            elif node.func.attr == "pop":
                popped.add(node.func.value.attr)
    return pushed & popped


def self_attribute_writes(fn):
    """Every `self.<x>` name `fn` assigns, with `=`, an annotation or `op=`."""
    names = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if is_self_attr(target):
                names.add(target.attr)
    return names


# Generator state that lives for the whole module rather than one function,
# grouped by why. With FIELDS and SHARED_WITH_NESTED_BODIES this classifies
# EVERY attribute a generator method assigns, so a new kind of state lands
# unclassified — and fails here — until someone decides which it is.
MODULE_STATE = {
    "the compile's options, target and LLVM module": (
        "namespace", "opt_level", "freestanding", "runtime_build",
        "target_features", "triple", "_explicit_target",
        "_seams_external_only", "_strip_unreachable", "llvm_context",
        "target_data", "int_width", "int_type", "module",
    ),
    "symbols declared once per module and looked up by name": (
        "functions", "compiler_declared_c_symbols", "static_globals",
        "abort", "printf", "snprintf", "strcat", "strcpy", "saw_panic",
        "saw_write", "pthread_tramp_type", "_argc_global", "_argv_global",
        "_exported_llvm_globals", "_synth_symbol_counts", "string_constants",
        "string_literal_globals", "_raw_byte_globals", "_bool_range_md",
        "_overflow_intrinsics", "_panic_helpers", "_blk_thunks",
        "_bt_table_global", "bt_table_bytes",
    ),
    "keyed by the llvm function's name, so a nested body has its own entries": (
        "_panic_scratch_slots", "_di_func_basename", "_di_loc_cache",
        "_di_stmt_lines", "_di_func_subprograms",
    ),
    "the module's debug-info unit": (
        "_di_cu", "_di_enabled", "_di_files", "_di_source_path",
        "_di_subroutine_type",
    ),
    "type, generic and vtable tables keyed by type or declaration": (
        "struct_types", "enum_types", "mono_struct_args", "mono_enum_args",
        "mono_registry", "generic_functions", "generic_structs",
        "generic_enums", "generic_extensions", "specialized_extensions",
        "plain_generic_methods", "generated_instantiations",
        "type_cleanup_behavior", "type_field_cleanup",
        "extern_optional_returns", "method_defaults", "func_defaults",
        "_aggregate_receiver_cache", "_abi_size_cache", "_abi_align_cache",
        "_unregistered_type_decls", "_deferred_type_bodies",
        "_draining_type_bodies", "_identity_env_cache", "_type_ids",
        "_pending_vtables", "_vtable_dtors", "_vtable_globals",
        "_vtable_thunks",
    ),
    "the body schedule, which runs one named body at a time": (
        "_bodies_deferred", "_bodies_emitted", "_deferred_bodies",
        "_reachable_symbols", "_scanned_symbols",
    ),
    "keyed by the closure literal's node id": (
        "closure_values",
    ),
}


# --------------------------------------------------------------------------- #
# The record's two tables
# --------------------------------------------------------------------------- #

def read_tables(closures_tree):
    """(FIELDS names, names with a fresh-body factory, SHARED reasons) or None."""
    cls = find_class(closures_tree, RECORD)
    if cls is None:
        return None
    fields, blanked, shared = [], [], {}
    for stmt in cls.body:
        if not isinstance(stmt, ast.Assign):
            continue
        target = stmt.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if target.id == "FIELDS" and isinstance(stmt.value, ast.Tuple):
            for element in stmt.value.elts:
                if (isinstance(element, ast.Tuple) and len(element.elts) == 3
                        and isinstance(element.elts[0], ast.Constant)):
                    name = element.elts[0].value
                    fields.append(name)
                    factory = element.elts[2]
                    installed = (
                        (isinstance(factory, ast.Constant)
                         and factory.value is None)
                        or (isinstance(factory, ast.Name)
                            and factory.id == "INSTALLED"))
                    if not installed:
                        blanked.append(name)
        elif target.id == "SHARED_WITH_NESTED_BODIES" and isinstance(stmt.value, ast.Dict):
            for key, value in zip(stmt.value.keys, stmt.value.values):
                if isinstance(key, ast.Constant):
                    shared[key.value] = ast.literal_eval(value) if isinstance(
                        value, (ast.Constant, ast.JoinedStr, ast.BinOp)) else ""
    return fields, blanked, shared


def check_tables(fields, blanked, shared):
    problems = []
    if not fields:
        problems.append(
            f"{RECORD}.FIELDS is empty or unreadable — it is the ONE table both "
            f"halves of the save/restore read, and every check below is about "
            f"it.")
    if len(fields) != len(set(fields)):
        problems.append(f"{RECORD}.FIELDS names a field twice")
    if not blanked:
        problems.append(
            f"no field in {RECORD}.FIELDS carries a fresh-body factory, so a "
            f"nested body would start from the enclosing function's bindings")
    for name, reason in shared.items():
        if not isinstance(reason, str) or len(reason.strip()) < 20:
            problems.append(
                f"{RECORD}.SHARED_WITH_NESTED_BODIES[{name!r}] carries no "
                f"reason. An entry there is a claim that a nested body may see "
                f"the enclosing function's value of it; write why.")
    overlap = set(shared) & set(fields)
    if overlap:
        problems.append(
            f"{sorted(overlap)} is both saved and declared shared — the two "
            f"tables answer the same question and must not disagree")
    return problems


# --------------------------------------------------------------------------- #
# 1: capture/blank/restore are driven by the table
# --------------------------------------------------------------------------- #

def check_record_is_list_driven(closures_tree, fields):
    problems = []
    cls = find_class(closures_tree, RECORD)
    if cls is None:
        return [f"{RECORD} is gone from codegen/closures.py"]
    for name in DRIVEN_METHODS:
        fn = find_def(cls, name)
        if fn is None:
            problems.append(f"{RECORD}.{name} is gone; the record's three "
                            f"halves are what every entry point calls")
            continue
        reads_fields = any(
            isinstance(node, ast.Attribute) and node.attr == "FIELDS"
            for node in ast.walk(fn))
        if not reads_fields:
            problems.append(
                f"{RECORD}.{name} no longer reads FIELDS, so it carries its "
                f"own idea of which state matters — the drift this record "
                f"exists to end")
        for node in ast.walk(fn):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node.value in fields):
                problems.append(
                    f"{RECORD}.{name} names the field {node.value!r} directly. "
                    f"Every field goes through FIELDS or a later one will be "
                    f"handled in one method and forgotten in another.")
    return problems


# --------------------------------------------------------------------------- #
# 2: no nested-body site keeps a private save beside the record
# --------------------------------------------------------------------------- #

def check_sites_use_the_record(closures_tree, fields):
    problems = []
    for site in NESTED_BODY_SITES:
        fn = find_def(closures_tree, site)
        if fn is None:
            problems.append(f"codegen/closures.py has no `{site}`; it is a "
                            f"declared entry point of the state record")
            continue
        captures = restores = False
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if (node.func.attr == "capture"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == RECORD):
                    captures = True
                if node.func.attr == "restore":
                    restores = True
        if not captures:
            problems.append(f"`{site}` does not call {RECORD}.capture — a "
                            f"nested body that saves nothing leaks its own "
                            f"state into the enclosing function")
        if not restores:
            problems.append(f"`{site}` does not call `.restore` — the "
                            f"enclosing function would carry on with the "
                            f"nested body's state")
        # A private save beside the record is exactly how the two lists drifted.
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign):
                continue
            value = node.value
            if is_self_attr(value) and value.attr in fields:
                problems.append(
                    f"`{site}` saves `self.{value.attr}` by hand beside the "
                    f"record. Put it in {RECORD}.FIELDS instead; a hand-saved "
                    f"field is one nobody restores when the next one is added.")
    return problems


# --------------------------------------------------------------------------- #
# 3: the sibling census — prologues AND every scoped save/restore — agrees
#    with the record
# --------------------------------------------------------------------------- #

def scoped_state_census(trees):
    """attribute -> the sites that scope it, over every codegen file."""
    census = {}
    for rel, tree in trees.items():
        for cls_name, fn in generator_methods(tree):
            for attr in saved_and_restored(fn) | stack_scoped(fn):
                census.setdefault(attr, []).append(f"{rel}:{cls_name}.{fn.name}")
    return census


def attribute_universe(trees):
    """attribute -> the sites that assign it, over every generator method."""
    universe = {}
    for rel, tree in trees.items():
        for cls_name, fn in generator_methods(tree):
            for attr in self_attribute_writes(fn):
                universe.setdefault(attr, []).append(
                    f"{rel}:{cls_name}.{fn.name}")
    return universe


def check_every_attribute_is_classified(universe, census, methods_tree,
                                        fields, shared):
    problems = []
    module = {}
    for reason, names in MODULE_STATE.items():
        for name in names:
            if name in module:
                problems.append(f"MODULE_STATE lists `{name}` twice")
            module[name] = reason
    for attr in sorted(universe):
        homes = [table for table, names in (("FIELDS", fields),
                                            ("SHARED_WITH_NESTED_BODIES", shared),
                                            ("MODULE_STATE", module))
                 if attr in names]
        if not homes:
            sites = ", ".join(universe[attr][:3])
            problems.append(
                f"`self.{attr}` is generator state ({sites}) that nothing "
                f"classifies. If a function's generation sets or scopes it, "
                f"put it in {RECORD}.FIELDS with its policies or in "
                f"SHARED_WITH_NESTED_BODIES with the reason a nested body may "
                f"see the enclosing value; if it lives for the whole module, "
                f"add it to this lane's MODULE_STATE under the reason.")
        elif len(homes) > 1:
            problems.append(f"`self.{attr}` is classified twice ({homes}); the "
                            f"tables answer one question and must not disagree")
    prologue_attrs = set()
    for node in ast.walk(methods_tree):
        if isinstance(node, ast.FunctionDef):
            names = self_assign_targets(node)
            if PROLOGUE_MARKER in names:
                prologue_attrs.update(names)
    for attr in sorted((set(census) | prologue_attrs) & set(module)):
        problems.append(
            f"MODULE_STATE lists `{attr}`, but codegen scopes it to an extent "
            f"of generation or resets it per function — it is per-function "
            f"state, and a nested body either isolates or shares it")
    for attr in sorted(set(module) - set(universe)):
        problems.append(f"MODULE_STATE lists `{attr}`, which no generator "
                        f"method assigns any more; remove the entry")
    return problems


def check_prologues(methods_tree, fields, shared):
    problems = []
    prologues = []
    for node in ast.walk(methods_tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        names = self_assign_targets(node)
        if PROLOGUE_MARKER in names:
            prologues.append((node.name, names))
    if not prologues:
        return [f"codegen/methods.py has no body generator that initializes "
                f"`self.{PROLOGUE_MARKER}`. Either the prologues moved or this "
                f"lane's marker is stale — update it rather than dropping it, "
                f"since it is the only thing comparing the two files."]
    known = set(fields) | set(shared)
    for fn_name, names in prologues:
        for attr in sorted(set(names)):
            if attr not in known:
                problems.append(
                    f"`{fn_name}` initializes `self.{attr}` per function, but "
                    f"{RECORD} neither saves it nor declares it shared. A "
                    f"closure body would inherit the enclosing function's "
                    f"value and leave its own behind: add it to FIELDS, or to "
                    f"SHARED_WITH_NESTED_BODIES with the reason that is safe.")
    return problems


def check_scoped_state(census, fields, shared):
    problems = []
    if not census:
        return ["no codegen method saves and restores a `self.<x>` — the "
                "census this lane runs found nothing, which means its "
                "definition of a save/restore no longer matches the code. "
                "Update the census rather than dropping it."]
    known = set(fields) | set(shared)
    for attr in sorted(census):
        if attr not in known:
            sites = ", ".join(census[attr][:3])
            problems.append(
                f"`self.{attr}` is scoped (saved and restored, or pushed and "
                f"popped) around an extent of "
                f"generation ({sites}), but {RECORD} neither isolates it nor "
                f"declares it shared. A nested body is another such extent, "
                f"with a whole function inside: put it in FIELDS with its "
                f"policies, or in SHARED_WITH_NESTED_BODIES with the reason a "
                f"nested body may see the enclosing value.")
    return problems


# --------------------------------------------------------------------------- #
# 4: every named attribute is real generator state, and no shared entry is
#    stale
# --------------------------------------------------------------------------- #

def check_names_exist(trees, methods_tree, census, fields, shared):
    held = set()
    for tree in trees.values():
        for node in ast.walk(tree):
            if is_self_attr(node):
                held.add(node.attr)
    problems = [f"{RECORD}.FIELDS names `{name}`, which codegen never touches "
                f"— a typo saves and restores nothing"
                for name in fields if name not in held]
    prologue_attrs = set()
    for node in ast.walk(methods_tree):
        if isinstance(node, ast.FunctionDef):
            names = self_assign_targets(node)
            if PROLOGUE_MARKER in names:
                prologue_attrs.update(names)
    for name in shared:
        if name not in census and name not in prologue_attrs:
            problems.append(
                f"{RECORD}.SHARED_WITH_NESTED_BODIES[{name!r}] describes state "
                f"no prologue initializes and no method scopes any more. A "
                f"claim about state that is gone is a claim nobody reviews: "
                f"remove the entry.")
    return problems


# --------------------------------------------------------------------------- #
# 5: a name off the table breaks a real compile
# --------------------------------------------------------------------------- #

# Each pin exercises the kinds of state its row names through a closure.
VOID_PIN = os.path.join(
    "examples", "closure_leaves_enclosing_void_local_visible.saw")
TEMPS_PIN = os.path.join(
    "examples", "closure_body_owns_its_own_statement_temporaries.saw")
CATCH_PIN = os.path.join(
    "examples",
    "closure_propagates_to_its_own_result_not_the_enclosing_catch.saw")
# (program, shape, field). `drop` takes the field off the restore only — the
# half-wired shape, where the enclosing function loses its state. `share`
# takes it off blank and restore both — the unlisted shape, where the nested
# body inherits the enclosing function's state and leaves its own in it.
# `snapshot` captures an identity field by copy, so the enclosing function
# gets back a list no frame above it drains; that compiles, so its failure
# is the program's output departing from what the pin expects.
INJECTIONS = (
    (VOID_PIN, "drop", "void_variables"),
    (VOID_PIN, "drop", "variables"),
    (TEMPS_PIN, "share", "statement_temps"),
    (TEMPS_PIN, "snapshot", "statement_temps"),
    (CATCH_PIN, "share", "_catch_context"),
)
ENV_FOR_SHAPE = {"drop": "SAW_CLOSURE_STATE_DROP",
                 "share": "SAW_CLOSURE_STATE_SHARE",
                 "snapshot": "SAW_CLOSURE_STATE_SNAPSHOT"}
WHERE_FOR_SHAPE = {"drop": "taking `{}` off the restore",
                   "share": "taking `{}` off both halves",
                   "snapshot": "capturing `{}` by copy"}
# Injected before this line in `FunctionCodegenState.capture`, and undone after.
CAPTURE_ANCHOR = "            saved[state_field] = value\n"
CAPTURE_INJECTION = (
    "            import os as _saw_probe_os\n"
    "            if (state_field == _saw_probe_os.environ.get(\n"
    "                    'SAW_CLOSURE_STATE_SNAPSHOT') and value is not None):\n"
    "                value = type(value)(value)\n")
# Injected beneath these lines in `FunctionCodegenState.blank` and `.restore`,
# and undone after.
BLANK_ANCHOR = "        for state_field, _policy, factory in self.FIELDS:\n"
BLANK_INJECTION = (
    "            import os as _saw_probe_os\n"
    "            if state_field == _saw_probe_os.environ.get(\n"
    "                    'SAW_CLOSURE_STATE_SHARE'):\n"
    "                continue\n")
RESTORE_ANCHOR = "        for state_field, _policy, _factory in self.FIELDS:\n"
RESTORE_INJECTION = (
    "            import os as _saw_probe_os\n"
    "            if state_field in (\n"
    "                    _saw_probe_os.environ.get('SAW_CLOSURE_STATE_DROP'),\n"
    "                    _saw_probe_os.environ.get('SAW_CLOSURE_STATE_SHARE')):\n"
    "                continue\n")


def _run_sawc(program, shape=None, field=None):
    env = dict(os.environ)
    env.pop("SAW_DEBUG", None)
    for var in ENV_FOR_SHAPE.values():
        env.pop(var, None)
    if shape is not None:
        env[ENV_FOR_SHAPE[shape]] = field
    out = os.path.join(REPO, ".build", "scratch", "closure_state_probe")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    compiled = subprocess.run(
        [sys.executable, SAWC_MAIN, program, "-o", out],
        capture_output=True, text=True, cwd=REPO, env=env)
    if compiled.returncode != 0:
        return compiled, None
    ran = subprocess.run([out], capture_output=True, text=True, cwd=REPO,
                         timeout=120)
    return compiled, ran


def expected_output(program):
    """The pin's EXPECT-OUTPUT block, one line per `// ` comment line."""
    lines, inside = [], False
    with open(os.path.join(REPO, program)) as fh:
        for line in fh:
            if line.startswith("// EXPECT-OUTPUT:"):
                inside = True
            elif inside and line.startswith("// "):
                lines.append(line[3:].rstrip("\n"))
            elif inside:
                break
    return "\n".join(lines)


def behaves(program, ran):
    return (ran is not None and ran.returncode == 0
            and ran.stdout.rstrip("\n") == expected_output(program))


def check_a_missing_field_breaks_the_compile():
    with open(CLOSURES) as fh:
        original = fh.read()
    for anchor, half in ((CAPTURE_ANCHOR, "capture"), (BLANK_ANCHOR, "blank"),
                         (RESTORE_ANCHOR, "restore")):
        if anchor not in original:
            return [f"the injection anchor for `{RECORD}.{half}`'s loop over "
                    f"FIELDS is gone. Update this test rather than dropping "
                    f"the check — a structural claim that the record has a "
                    f"table is not a claim that the table is what the compile "
                    f"depends on."]
    programs = sorted({program for program, _shape, _field in INJECTIONS})
    for program in programs:
        if not os.path.exists(os.path.join(REPO, program)):
            return [f"{program} is gone; the regression needs the program "
                    f"that exercises its kind of state across a closure."]
    problems = []
    try:
        with open(CLOSURES, "w") as fh:
            fh.write(original
                     .replace(CAPTURE_ANCHOR,
                              CAPTURE_INJECTION + CAPTURE_ANCHOR, 1)
                     .replace(BLANK_ANCHOR, BLANK_ANCHOR + BLANK_INJECTION, 1)
                     .replace(RESTORE_ANCHOR,
                              RESTORE_ANCHOR + RESTORE_INJECTION, 1))

        for program in programs:
            control, ran = _run_sawc(program)
            if control.returncode != 0:
                problems.append(
                    f"{program} fails to compile with nothing taken off the "
                    f"table (exit {control.returncode}): either the injection "
                    f"itself broke it, or the table is already missing a kind "
                    f"of state the program crosses a closure with. The "
                    f"injections below prove nothing until this "
                    f"compiles:\n{(control.stdout + control.stderr)[:600]}")
            elif not behaves(program, ran):
                problems.append(
                    f"{program} compiles with nothing taken off the table but "
                    f"does not print its EXPECT-OUTPUT, so an injection's "
                    f"departure from it would prove nothing")

        for program, shape, field in INJECTIONS:
            compiled, ran = _run_sawc(program, shape, field)
            text = (compiled.stdout + compiled.stderr).strip()
            where = WHERE_FOR_SHAPE[shape].format(field)
            if compiled.returncode == 0 and behaves(program, ran):
                problems.append(
                    f"{where} left {program} compiling and printing what it "
                    f"expects. Either it is not really per-function state, "
                    f"its policy is not load-bearing, or the pin stopped "
                    f"exercising it — the table is only a guarantee while "
                    f"every entry on it is load-bearing.")
            elif "Traceback (most recent call last)" in text:
                problems.append(
                    f"{where} printed a raw Python traceback rather than "
                    f"going through the internal-compiler-error "
                    f"report:\n{text[:400]}")
    finally:
        with open(CLOSURES, "w") as fh:
            fh.write(original)
    return problems


def main():
    trees = {os.path.relpath(path, REPO): parse(path)
             for path in codegen_files()}
    closures_tree = trees[os.path.relpath(CLOSURES, REPO)]
    methods_tree = trees[os.path.relpath(METHODS, REPO)]

    tables = read_tables(closures_tree)
    if tables is None:
        print("CLOSURE-STATE GATE FAILED")
        print()
        print(f"  codegen/closures.py has no `{RECORD}` class. The per-function "
              f"state a nested body saves and restores lives in ONE record; "
              f"without it the save and the restore are two hand-maintained "
              f"lists again (SL-356).")
        return 1
    fields, blanked, shared = tables
    census = scoped_state_census(trees)
    universe = attribute_universe(trees)

    problems = check_tables(fields, blanked, shared)
    problems += check_every_attribute_is_classified(
        universe, census, methods_tree, fields, shared)
    problems += check_record_is_list_driven(closures_tree, fields)
    problems += check_sites_use_the_record(closures_tree, fields)
    problems += check_prologues(methods_tree, fields, shared)
    problems += check_scoped_state(census, fields, shared)
    problems += check_names_exist(trees, methods_tree, census, fields, shared)
    problems += check_a_missing_field_breaks_the_compile()

    if problems:
        print("CLOSURE-STATE GATE FAILED")
        print()
        for problem in problems:
            print(f"  {problem}")
        print()
        print("A closure body is a second function emitted inside the first.")
        print("Every kind of per-function state it blanks, it owes back — and")
        print("one table is what says which kinds there are (SL-356).")
        return 1

    print(f"closure-state gate: {len(fields)} kinds of per-function state on "
          f"one table ({len(blanked)} started fresh for a nested body), "
          f"{len(shared)} declared shared with a reason, "
          f"{len(census)} kinds of scoped state in the census, all "
          f"{len(universe)} generator attributes classified, "
          f"{len(NESTED_BODY_SITES)} nested-body sites on the record, the "
          f"prologues agree, and each of {len(INJECTIONS)} injections breaks "
          f"a real compile or its output.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
