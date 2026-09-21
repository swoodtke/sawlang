#!/usr/bin/env python3
"""The coroutine transform asks ONE ledger, and nothing else, about a frame.

Design 275 U1 (SL-318). This is the enumeration gate that keeps
`sawc/coro_transform.py` from growing a twenty-first predicate that re-derives
"does this callee suspend / what key names its frame / can I build it" out of the
raw inputs.

WHY IT EXISTS. Every coroutine-transform finding of the week of Sep 14 was two
readings of those raw inputs disagreeing, not a lowering bug: SL-280 found SIX
sites keying a callee's frame independently (three read a written `name`, three
read `mangled_symbol or name`, and design 249 tags only a module-PRIVATE free
function); SL-274's review found two MORE the funnel had not reached; SL-306
found the call-site classifier, the closure walk and generic promotion asking
three different suspension questions; and SL-306's OWN review found a fourth
reader of the broad bit the sweep had missed. Each fix routed the found site and
named its entries, and each following unit found a sibling the enumeration
missed — twice in one day, by review rather than by gate. A decision re-derived
at every consumer cannot be audited by reading; a recorded decision can be
audited by a test.

WHAT IS CHECKED:

  1. NO RAW ATTRIBUTE READ outside the ledger's builder. `.suspends`,
     `.mangled_symbol`, `.resolved_symbol`, `.module_free_call`, `.mangled_name`
     and `.coro_frame_key`, in the attribute form AND in the
     `getattr(x, '<name>', …)` / `hasattr` form, which is how most of them were
     actually spelled.
  2. NO RAW ANSWER NAME outside the builder. `callee_frame_key`,
     `method_frame_key`, `classify_suspensions`, the five design-275-U4
     derivations, `_suspend_nodes`, and the four suspending-method censuses. A
     consumer that wants one of these answers asks the ledger for it.
  3. NO CALLEE `.name` USED AS A KEY outside the builder — a `.name` read that
     flows into a membership test, a subscript or a `.get()` lookup. This is
     SL-280's mechanism exactly, and it is the one the other two checks cannot
     see: `funcs_by_name[fc.name]` names no banned attribute and no banned
     function. A `.name` passed to a message, to a blocking-extern lookup or to
     the ledger's own composer is untouched; `_SUSPEND_CALLS` is allowlisted,
     because the suspend PRIMITIVES are a fixed list of written names and not a
     frame table.
  4. EVERY NAMED CONSUMER READS THE LEDGER. The census in `FrameLedger`'s
     docstring lists them; this checks each one actually references `ledger` /
     `self._ledger`, so a consumer cannot be quietly un-routed while its row
     stays in the table.
  5. THE COMPOSERS HAVE EXACTLY ONE CALLING MODULE. `callee_frame_key` and
     `method_frame_key` are called from `coro_ledger.py` and nowhere else in
     `sawc/` — the sixteen named entry points SL-280 collected, collapsed to one.
  6. THE LEDGER FREEZES, AND ITS WRITERS SAY SO. `_build_frame_ledger` calls
     `ledger.freeze()`, and every `record_*` / `register_*` / `note_*` / `add_*`
     / `seed_*` / `drop_*` / `stamp_*` / `rename_*` method of `FrameLedger` calls
     `self._open(...)` — so a write after discovery is an invariant failure
     rather than a silently late table entry.
  7. THE MISS IS AN INVARIANT FAILURE, structurally. `FrameLedger.frame` and
     `free_call_frame` both raise `LedgerMiss`, `_record_frame_decisions` is
     called UNCONDITIONALLY (the dump flag decides only whether the text is
     rendered), and `sawc.py` catches the exception. A ledger miss must never be
     permission to emit a plain call — that silent decline is what this epic
     exists to end.
  8. THE MISS IS AN INVARIANT FAILURE, in a REAL COMPILE. The structural check
     above is what codex's SL-318.p4 r1 review found insufficient on the first
     draft: the gate passed because `frame()` contained a raise, not because a
     consumer miss reached it. So this DROPS one recorded decision — by injecting
     a skip into `FrameLedger.record_frame` and restoring it in a `finally`, the
     house pattern `test_ice_breadcrumb.py` established — compiles a real
     example whose driven body calls that callee, and requires the
     internal-compiler-error line to NAME the dropped key. The same compile with
     nothing dropped must still succeed, so the injection is the only difference.
  9. EVERY DRIVEN-ROOT FAMILY IS IN THE SITE CENSUS. Codex's P2: the census
     walked the free closure and the embedded methods, and driven METHOD ROOTS
     are kept out of `method_closure`, so their FRAME rows appeared beside
     `# sites: 0` whatever their bodies contained. This runs
     `--emit-frame-ledger` on one program per root family — a plain driven
     method, a driven method on a GENERIC STRUCT, and a METHOD-LEVEL generic —
     and requires the frame row AND at least one `context=driven root` site row
     in each.

Run from the repo root:  ./.venv/bin/python tools/test_coro_discovery.py
Exit code 0 = pass; nonzero (with a diagnostic) = fail.
"""
import ast
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAWC = os.path.join(REPO, "sawc")
SAWC_MAIN = os.path.join(SAWC, "sawc.py")
TRANSFORM = os.path.join(SAWC, "coro_transform.py")
LEDGER = os.path.join(SAWC, "coro_ledger.py")

# The ledger's BUILDER — named by FUNCTION, never by a line range, so moving the
# code does not silently widen the exemption. Everything lexically inside this
# function (its nested `def`s included) may touch the raw inputs; nothing else
# in the module may.
BUILDER_REGION = ("_build_frame_ledger",)

# 1. Attribute names that ARE the raw discovery inputs.
RAW_ATTRS = {
    "suspends":         "an effect node's suspension answer",
    "mangled_symbol":   "a declaration's overload/module symbol",
    "resolved_symbol":  "a call site's resolved overload symbol",
    "module_free_call": "SL-208's module-qualified free-call marker",
    "mangled_name":     "a namespace symbol's mangled name",
    "coro_frame_key":   "the frame key generic promotion stamps on a call",
}

# 2. Names that answer a discovery question directly.
RAW_NAMES = {
    "callee_frame_key":  "the free-function key COMPOSER (ask the ledger)",
    "method_frame_key":  "the method key COMPOSER (ask the ledger)",
    "classify_suspensions": "the design-275-U4 analysis (the ledger holds it)",
    "frame_boundary":    "a U4 derivation (ask `free_boundary` / "
                         "`edge_is_boundary` / `instantiation_is_boundary`)",
    "might_suspend":     "a U4 derivation (ask `might_suspend_free`)",
    "wraps_main":        "a U4 derivation",
    "refused_in_thread_body": "a U4 derivation",
    "closure_only":      "a U4 derivation",
    "_suspend_nodes":    "the raw effect graph",
    "_suspending_methods_set": "the retired broad method census",
    "_own_suspending_methods_set": "the retired own method census",
    "_really_suspending_methods_set": "a census design 206 retired",
    "_std_suspending_methods": "the builtin compile's broad seed",
    "_std_suspending_methods_ignoring_closure_calls":
        "the builtin compile's own seed",
}

# 3. The FRAME-KEY tables. A `.name` read reaching one of these is SL-280's
# mechanism; a `.name` reaching `encmap`, `frame_locals` or any other
# BINDING-name table is ordinary lowering and is none of this gate's business,
# which is why the check names the tables rather than the `.name` reads.
FRAME_TABLES = {
    "fbs", "spawn_fbs", "funcs_by_name", "closure", "removed", "consumed",
    "roots", "method_roots", "spawn_roots", "bg_spawn_roots", "mt_spawn_roots",
    "dual_role_spawn_roots", "_drop", "spliced_keys", "templates", "live",
    "readded", "methods_by_key", "methods_by_id", "method_closure",
    "mono_recv_types", "free_bodies", "imported_free_bodies",
    "mono_free_bodies", "mono_method_bodies",
}

# 4. The consumers the ledger's docstring census names. Each must reference the
# ledger; `(class-or-None, function)`.
CONSUMERS = [
    ("_FrameBuilder", "__init__"),
    ("_FrameBuilder", "_is_suspension_point"),
    ("_FrameBuilder", "_spans_suspension"),
    ("_FrameBuilder", "_classify_call"),
    ("_FrameBuilder", "_classify_method_call"),
    ("_FrameBuilder", "_module_free_call_suspends"),
    ("_FrameBuilder", "_method_call_suspends"),
    ("_FrameBuilder", "_suspending_method_call"),
    ("_FrameBuilder", "_reject_buried_suspend_call"),
    (None, "_default_expr_suspends"),
    (None, "_find_suspending_cycle"),
    (None, "_analyze_nesting"),
    (None, "_promote_nested_generic_calls"),
    (None, "_promote_nested_generic_methods"),
    (None, "_rewrite_drive_sites"),
    (None, "_called_function_names"),
    (None, "_names_the_survivors_call"),
    (None, "_consume_templates_naming_removed"),
    (None, "transform_program"),
]

LEDGER_WRITER_PREFIXES = ("record_", "register_", "note_", "add_", "seed_",
                          "drop_", "stamp_", "rename_")


def parse(path):
    with open(path) as fh:
        return ast.parse(fh.read(), filename=path)


# --------------------------------------------------------------------------- #
# Scope map: every node -> the top-level function/method it sits in
# --------------------------------------------------------------------------- #

def scope_map(tree):
    """node -> (class_name or None, top-level def name or None).

    A nested `def` belongs to the enclosing TOP-LEVEL one, which is what makes
    the builder region a single name rather than a name per nested closure.
    """
    out = {}

    def walk(node, cls, fn):
        for child in ast.iter_child_nodes(node):
            c, f = cls, fn
            if isinstance(child, ast.ClassDef):
                c, f = child.name, None
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if f is None:
                    f = child.name
            out[child] = (c, f)
            walk(child, c, f)

    out[tree] = (None, None)
    walk(tree, None, None)
    return out


def in_builder(scope):
    return scope[1] in BUILDER_REGION


# --------------------------------------------------------------------------- #
# 1 + 2 + 3: the raw reads
# --------------------------------------------------------------------------- #

def _where(scope):
    cls, fn = scope
    if cls and fn:
        return f"{cls}.{fn}"
    return fn or "<module>"


def check_raw_reads(tree, scopes):
    problems = []
    for node in ast.walk(tree):
        scope = scopes.get(node, (None, None))
        if in_builder(scope):
            continue

        # 1a. `x.<raw>`
        if isinstance(node, ast.Attribute) and node.attr in RAW_ATTRS:
            problems.append(
                f"coro_transform.py:{node.lineno}: {_where(scope)} reads "
                f"`.{node.attr}` ({RAW_ATTRS[node.attr]}) directly. Ask the "
                f"discovery ledger instead (design 275 U1).")

        # 1b. `getattr(x, '<raw>', …)` / `hasattr(x, '<raw>')`
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("getattr", "hasattr")
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in RAW_ATTRS):
            raw = node.args[1].value
            problems.append(
                f"coro_transform.py:{node.lineno}: {_where(scope)} reads "
                f"`{node.func.id}(..., '{raw}')` ({RAW_ATTRS[raw]}). Ask the "
                f"discovery ledger instead (design 275 U1).")

        # 2. a raw ANSWER name, however it is reached
        ident = None
        if isinstance(node, ast.Name):
            ident = node.id
        elif isinstance(node, ast.Attribute):
            ident = node.attr
        if ident in RAW_NAMES:
            problems.append(
                f"coro_transform.py:{node.lineno}: {_where(scope)} names "
                f"`{ident}` — {RAW_NAMES[ident]}. The ledger is the one reader "
                f"(design 275 U1).")

        # 3. a callee's `.name` used as a KEY
        problems += _name_as_key(node, scope)
    return problems


def _is_name_read(node):
    """Is `node` a read of some object's `.name`, in either spelling?"""
    if isinstance(node, ast.Attribute) and node.attr == "name":
        return True
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == "name")


def _table_id(node):
    """The NAME of the collection `node` denotes, for the frame-table test."""
    return getattr(node, 'id', None) or getattr(node, 'attr', None)


def _name_as_key(node, scope):
    if not isinstance(node, (ast.Compare, ast.Subscript, ast.Call)):
        return []
    problems = []

    def complain(table):
        return (f"coro_transform.py:{node.lineno}: {_where(scope)} looks `{table}` "
                f"up by a node's written `.name`. That is SL-280's mechanism: a "
                f"frame table is keyed by FRAME KEY, and a callee whose "
                f"registration stamped a symbol is filed under a key no written "
                f"name matches — so the miss reads as `does not suspend` and the "
                f"park lowers in place. Ask the ledger for the key.")

    if isinstance(node, ast.Compare):
        for op, comparator in zip(node.ops, node.comparators):
            if not isinstance(op, (ast.In, ast.NotIn)):
                continue
            if not _is_name_read(node.left):
                continue
            table = _table_id(comparator)
            if table in FRAME_TABLES:
                problems.append(complain(table))
    if (isinstance(node, ast.Subscript) and _is_name_read(node.slice)
            and _table_id(node.value) in FRAME_TABLES):
        problems.append(complain(_table_id(node.value)))
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get" and node.args
            and _is_name_read(node.args[0])
            and _table_id(node.func.value) in FRAME_TABLES):
        problems.append(complain(_table_id(node.func.value)))
    return problems


def check_no_composer_import(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "frame_keys":
            return [f"coro_transform.py:{node.lineno}: imports from "
                    f"`frame_keys`. The key composer belongs to the ledger and "
                    f"has one caller (design 275 U1)."]
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "frame_keys":
                    return [f"coro_transform.py:{node.lineno}: imports "
                            f"`frame_keys`; the composer is the ledger's."]
    return []


# --------------------------------------------------------------------------- #
# 4: the consumers are on the funnel
# --------------------------------------------------------------------------- #

def find_def(tree, cls_name, fn_name):
    if cls_name is None:
        for node in tree.body:
            if (isinstance(node, ast.FunctionDef) and node.name == fn_name):
                return node
        return None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            for m in node.body:
                if isinstance(m, ast.FunctionDef) and m.name == fn_name:
                    return m
    return None


def check_consumers_read_the_ledger(tree):
    problems = []
    for cls_name, fn_name in CONSUMERS:
        fn = find_def(tree, cls_name, fn_name)
        if fn is None:
            problems.append(
                f"coro_transform.py: the ledger's consumer census names "
                f"`{cls_name + '.' if cls_name else ''}{fn_name}`, which no "
                f"longer exists. A census that does not match the module is the "
                f"thing this gate replaces — fix one or the other.")
            continue
        names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
        if "ledger" not in names and "_ledger" not in attrs:
            problems.append(
                f"coro_transform.py:{fn.lineno}: "
                f"`{cls_name + '.' if cls_name else ''}{fn_name}` is on the "
                f"ledger's consumer census and does not read the ledger. Route "
                f"it, or take its row out of the census (design 275 U1).")
    return problems


# --------------------------------------------------------------------------- #
# 5: the composers have one calling module
# --------------------------------------------------------------------------- #

# 5. WHO MAY COMPOSE A FRAME KEY, and how many times.
#
# SL-280 collected SIXTEEN named entry points; design 275 U1 collapses the
# TRANSFORM's fifteen to one — the ledger — and leaves the PRODUCERS, which
# cannot ask a ledger that does not exist yet: the effect graph's node and edge
# keys are composed while the graph is being BUILT, and the driven/spawn root
# recording happens in the typechecker so that `roots`/`spawn_roots` live in the
# same key space as the tables the transform looks them up in.
#
# The COUNT is part of the allowlist. A sixth call anywhere fails, which is what
# makes this an enumeration rather than a naming convention.
COMPOSER_CALLERS = {
    "sawc/coro_ledger.py": (9, "THE ledger: the composers' one caller in the "
                               "transform's half of the compiler — the two "
                               "registrations, the four `*_key*` methods of the "
                               "read API, `free_call_frame`, "
                               "`free_body_of_call`, and design 275 U2's "
                               "`unbuildable_callee` (SL-287's refusal read)"),
    "sawc/typechecker/effects.py": (2, "the effect graph's NODE key "
                                       "(`_effect_enter_function`) and EDGE key "
                                       "(`_effect_call_function`)"),
    "sawc/typechecker/expressions.py": (2, "the driven-root recording "
                                           "(`_effect_record_driven`) and the "
                                           "spawn-root recording "
                                           "(`_check_spawned_call_argument`)"),
}


def check_composers_have_one_caller():
    problems = []
    counts = {}
    for dirpath, dirnames, filenames in os.walk(SAWC):
        dirnames[:] = [d for d in sorted(dirnames)
                       if d not in ("__pycache__", "std", "rt")]
        for fn in sorted(filenames):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, REPO).replace(os.sep, "/")
            if rel == "sawc/frame_keys.py":
                continue          # the definition itself
            try:
                tree = parse(path)
            except SyntaxError as e:
                problems.append(f"{rel}: could not parse ({e})")
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                called = (getattr(node.func, 'id', None)
                          or getattr(node.func, 'attr', None))
                if called not in ("callee_frame_key", "method_frame_key"):
                    continue
                counts[rel] = counts.get(rel, 0) + 1
                if rel not in COMPOSER_CALLERS:
                    problems.append(
                        f"{rel}:{node.lineno}: calls `{called}`. Composing a "
                        f"frame key is the DISCOVERY LEDGER's job, plus the three "
                        f"producers that build the graph and record the roots. A "
                        f"new site is SL-280's mechanism with a new way in "
                        f"(design 275 U1).")
    for rel, (expected, why) in COMPOSER_CALLERS.items():
        got = counts.get(rel, 0)
        if got != expected:
            problems.append(
                f"{rel}: composes a frame key {got} time(s), expected "
                f"{expected} ({why}). The COUNT is part of the allowlist — "
                f"update it deliberately, with the reason, or route the new site "
                f"through the ledger.")
    return problems


# --------------------------------------------------------------------------- #
# 6 + 7: the freeze and the invariant failure
# --------------------------------------------------------------------------- #

def check_freeze_and_invariants(transform_tree, ledger_tree):
    problems = []
    builder = find_def(transform_tree, None, "_build_frame_ledger")
    if builder is None:
        problems.append("coro_transform.py: `_build_frame_ledger` is gone. The "
                        "gate's builder region is named by function; rename the "
                        "region here if the function moved.")
    else:
        froze = any(
            isinstance(n, ast.Call) and getattr(n.func, 'attr', None) == "freeze"
            for n in ast.walk(builder))
        if not froze:
            problems.append(
                "coro_transform.py: `_build_frame_ledger` never calls "
                "`ledger.freeze()`. Discovery FINISHES before any body is "
                "lowered; the freeze is what makes a later write an invariant "
                "failure rather than a silently late table entry.")

    ledger_cls = None
    for node in ledger_tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "FrameLedger":
            ledger_cls = node
    if ledger_cls is None:
        problems.append("coro_ledger.py: `FrameLedger` is gone.")
        return problems

    writers = []
    for m in ledger_cls.body:
        if not isinstance(m, ast.FunctionDef):
            continue
        if not m.name.startswith(LEDGER_WRITER_PREFIXES):
            continue
        writers.append(m.name)
        opens = any(
            isinstance(n, ast.Call) and getattr(n.func, 'attr', None) == "_open"
            for n in ast.walk(m))
        if not opens:
            problems.append(
                f"coro_ledger.py:{m.lineno}: `FrameLedger.{m.name}` writes the "
                f"ledger without calling `self._open(...)`, so it would succeed "
                f"after the freeze.")
    if not writers:
        problems.append("coro_ledger.py: `FrameLedger` has no writer methods; "
                        "the freeze check has nothing to police.")

    # BOTH strict reads must raise. `frame` is the explicit lookup; and
    # `free_call_frame` is the one on the LOWERING path — codex's SL-318.p4 r1
    # finding was that only the unused one raised, so the invariant was
    # decorative.
    for reader in ("frame", "free_call_frame"):
        fn = None
        for m in ledger_cls.body:
            if isinstance(m, ast.FunctionDef) and m.name == reader:
                fn = m
        if fn is None:
            problems.append(
                f"coro_ledger.py: `FrameLedger.{reader}` is gone — that is one "
                f"of the two reads whose MISS is the invariant failure.")
            continue
        raises = any(
            isinstance(n, ast.Raise)
            and getattr(getattr(n.exc, 'func', None), 'id', None) == "LedgerMiss"
            for n in ast.walk(fn))
        if not raises:
            problems.append(
                f"coro_ledger.py: `FrameLedger.{reader}` does not raise "
                f"`LedgerMiss` on a miss. A ledger miss is an INVARIANT "
                f"FAILURE, never permission to emit a plain call — and this is "
                f"the read the CLASSIFIERS ask (design 275 U1).")

    # The decisions must be recorded on EVERY compile: the dump flag decides
    # whether the TEXT is rendered, never whether the table exists.
    if builder is not None:
        for node in ast.walk(builder):
            if not isinstance(node, ast.If):
                continue
            guard_names = {getattr(n, 'attr', None) or getattr(n, 'id', None)
                           for n in ast.walk(node.test)}
            if "capture_enabled" not in guard_names:
                continue
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Call)
                        and getattr(inner.func, 'id', None)
                        == "_record_frame_decisions"):
                    problems.append(
                        f"coro_transform.py:{inner.lineno}: "
                        f"`_record_frame_decisions` is called under a "
                        f"`capture_enabled()` guard. Then an ordinary build has "
                        f"no decision table, a consumer's miss and a recorded "
                        f"`no-frame-owed` are one fact again, and the whole "
                        f"invariant is decorative (codex, SL-318.p4 r1). The "
                        f"flag decides only whether the dump TEXT is rendered.")

    sawc_tree = parse(os.path.join(SAWC, "sawc.py"))

    def _caught(node):
        """The exception names one `except` clause catches. A TUPLE counts —
        design 275 U2 put `coro_shapes.UnclassifiedShape` beside `LedgerMiss`
        there, both being invariant failures `_report_ice` renders the same
        way, and a check that only understood a bare name would have read that
        as the handler going missing."""
        if node.type is None:
            return ()
        parts = (node.type.elts if isinstance(node.type, ast.Tuple)
                 else [node.type])
        return tuple(getattr(p, 'attr', None) or getattr(p, 'id', None)
                     for p in parts)

    handled = any(
        isinstance(n, ast.ExceptHandler) and "LedgerMiss" in _caught(n)
        for n in ast.walk(sawc_tree))
    if not handled:
        problems.append(
            "sawc.py: nothing catches `coro_ledger.LedgerMiss`, so a ledger "
            "miss would reach the user as a raw Python traceback instead of "
            "design 192 unit 2's internal-compiler-error line.")
    return problems


# --------------------------------------------------------------------------- #
# 8: the miss invariant, in a real compile
# --------------------------------------------------------------------------- #

# The program: `outer -> mid -> inner`, all three driven, `inner` suspending.
# Dropping `inner$m$`'s decision leaves `mid`'s body calling a suspending callee
# the ledger has no row for, which is exactly the consumer path.
MISS_PROGRAM = os.path.join("examples", "coro_nested_suspend_two_deep.saw")
MISS_KEY = "inner$m$"
# Injected beneath this line in `FrameLedger.record_frame`, and restored after.
MISS_ANCHOR = '        self._open("a frame row")\n'
MISS_INJECTION = (
    '        import os as _saw_probe_os\n'
    '        if row.key == _saw_probe_os.environ.get("SAW_LEDGER_DROP_KEY"):\n'
    '            return\n')


def _run_sawc(drop_key=None):
    env = dict(os.environ)
    env.pop("SAW_DEBUG", None)
    if drop_key is None:
        env.pop("SAW_LEDGER_DROP_KEY", None)
    else:
        env["SAW_LEDGER_DROP_KEY"] = drop_key
    out = os.path.join(REPO, ".build", "scratch", "coro_discovery_miss_probe")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    return subprocess.run(
        [sys.executable, SAWC_MAIN, MISS_PROGRAM, "-o", out],
        capture_output=True, text=True, cwd=REPO, env=env)


def check_miss_reaches_a_consumer():
    """Drop ONE decision and require the named-key ICE from a real compile."""
    path = LEDGER
    with open(path) as fh:
        original = fh.read()
    if MISS_ANCHOR not in original:
        return [f"coro_ledger.py: the injection anchor for the miss regression "
                f"is gone (`record_frame`'s `_open` call). Update this test "
                f"rather than dropping the check — it is the only thing that "
                f"proves a consumer miss REACHES the invariant."]
    if not os.path.exists(os.path.join(REPO, MISS_PROGRAM)):
        return [f"{MISS_PROGRAM} is gone; the miss regression needs a driven "
                f"body that calls a suspending free callee."]
    problems = []
    try:
        with open(path, "w") as fh:
            fh.write(original.replace(
                MISS_ANCHOR, MISS_ANCHOR + MISS_INJECTION, 1))

        control = _run_sawc(drop_key=None)
        if control.returncode != 0:
            problems.append(
                f"the injection itself broke the compile with nothing dropped "
                f"(exit {control.returncode}), so the regression below proves "
                f"nothing:\n{(control.stdout + control.stderr)[:600]}")

        dropped = _run_sawc(drop_key=MISS_KEY)
        text = (dropped.stdout + dropped.stderr).strip()
        if dropped.returncode == 0:
            problems.append(
                f"dropping the decision for `{MISS_KEY}` compiled CLEANLY. A "
                f"ledger miss reached a consumer and was read as `does not "
                f"suspend` — the silent decline design 275 exists to end.")
        else:
            if "internal compiler error" not in text:
                problems.append(
                    f"dropping `{MISS_KEY}` failed without an internal-compiler-"
                    f"error line; a discovery gap must report as one:\n{text[:600]}")
            if MISS_KEY not in text:
                problems.append(
                    f"the report does not NAME `{MISS_KEY}`. The key is the "
                    f"whole point: it is what tells a compiler author which "
                    f"callee discovery missed:\n{text[:600]}")
            if "Traceback (most recent call last)" in text:
                problems.append(
                    "the miss printed a raw Python traceback at the user; it "
                    "must go through `_report_ice` like every other ICE.")
    finally:
        with open(path, "w") as fh:
            fh.write(original)
    return problems


# --------------------------------------------------------------------------- #
# 9: every driven-root family is in the site census
# --------------------------------------------------------------------------- #

# (program, the FRAME row that must be there, what the family is called)
ROOT_FAMILIES = [
    (os.path.join("examples", "coro_driving_method_self.saw"),
     "FRAME Counter_climb\t", "a plain driven METHOD root"),
    (os.path.join("examples", "coro_generic_struct_method.saw"),
     "FRAME Slot_settle$1$Int\t", "a driven method on a GENERIC STRUCT"),
    (os.path.join("examples", "coro_generic_method_self.saw"),
     "FRAME Counter_absorb$1$Slow\t", "a METHOD-LEVEL generic root"),
]


def check_driven_roots_are_in_the_site_census():
    problems = []
    for rel, frame_row, what in ROOT_FAMILIES:
        if not os.path.exists(os.path.join(REPO, rel)):
            problems.append(f"{rel} is gone; it pinned {what} in the site census")
            continue
        run = subprocess.run(
            [sys.executable, SAWC_MAIN, rel, "--emit-frame-ledger"],
            capture_output=True, text=True, cwd=REPO)
        if run.returncode != 0:
            problems.append(f"{rel}: --emit-frame-ledger failed:\n"
                            f"{(run.stdout + run.stderr)[:400]}")
            continue
        dump = run.stdout
        if frame_row not in dump:
            problems.append(
                f"{rel}: the dump has no `{frame_row.strip()}` row, so this "
                f"check no longer pins {what}. Update the expected key.")
        driven = [ln for ln in dump.splitlines()
                  if ln.startswith("SITE ") and "context=driven root" in ln]
        if not driven:
            problems.append(
                f"{rel}: the dump records NO `context=driven root` site for "
                f"{what}, though its frame row is present. A root's body is "
                f"lowered like any other, so every suspension in it is the "
                f"census's business — this is codex's P2 on SL-318.p4 r1, where "
                f"a frame row sat beside `# sites: 0`.")
    return problems


def main():
    transform_tree = parse(TRANSFORM)
    ledger_tree = parse(LEDGER)
    scopes = scope_map(transform_tree)

    problems = []
    problems += check_raw_reads(transform_tree, scopes)
    problems += check_no_composer_import(transform_tree)
    problems += check_consumers_read_the_ledger(transform_tree)
    problems += check_composers_have_one_caller()
    problems += check_freeze_and_invariants(transform_tree, ledger_tree)
    problems += check_miss_reaches_a_consumer()
    problems += check_driven_roots_are_in_the_site_census()

    if problems:
        print("CORO-DISCOVERY GATE FAILED")
        print()
        for p in problems:
            print(f"  {p}")
        print()
        print("A frame decision is made ONCE, recorded in the discovery ledger,")
        print("and read from there. Every coroutine-transform finding of the")
        print("week of Sep 14 was two readings of the raw inputs disagreeing")
        print("(design 275; SL-280, SL-274, SL-306 and its review).")
        return 1

    n_consumers = len(CONSUMERS)
    n_raw = len(RAW_ATTRS) + len(RAW_NAMES)
    print(f"coro-discovery gate: {n_raw} raw discovery inputs banned outside "
          f"`{BUILDER_REGION[0]}`, {n_consumers} consumers on the ledger, "
          f"2 key composers with one calling module, freeze + miss invariants "
          f"in place, a dropped decision reaches the ICE naming `{MISS_KEY}`, "
          f"{len(ROOT_FAMILIES)} driven-root families in the site census.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
