"""design 275 U1 — THE DISCOVERY LEDGER.

ONE authority for every question the coroutine transform asks about a callee.
Before this unit roughly twenty predicates in `coro_transform.py` each
re-derived "does this callee suspend / what key names its frame / can I build
it" from the RAW INPUTS — an effect node's cause set, `mangled_symbol`,
`resolved_symbol`, `module_free_call`, a callee node's written `name`, the two
suspending-method censuses, the entry and imported body tables, the generic
instantiation registry, the method tables. Every coroutine-transform finding of
the week of Sep 14 was two of those readings disagreeing: SL-280's six keying
sites, SL-274's review finding two more the funnel had not reached, SL-306's
classifier-versus-closure-walk split, and its own review finding a fourth reader
of the broad suspension bit. A decision re-derived at every consumer and policed
by reading is the shape design 275 exists to end, and the remedy the ownership
epic already proved one module over is a RECORDED decision with a gate.

So: `FrameLedger` is built ONCE per program, BEFORE any body is lowered, then
FROZEN, and every consumer READS it and derives nothing. `tools/test_coro_discovery.py`
(the `corodiscovery` battery lane) parses `coro_transform.py` and fails on any
site outside the ledger's builder that touches one of those raw inputs, which is
what turns "a missed sibling" from likely into impossible.

TWO TABLES, and the split is codex review point 2's. A `FrameRow` is a CALLEE
FACT: one row per frame key discovery reached, carrying what it concluded about
that callee once. A `SiteRow` is a CALL-SITE DECISION: one row per position a
suspension is reached from, carrying the CONTEXT that position sits in and the
OUTCOME the transform gives it there. The same callee is EMBED as a direct call
in a driven body and REFUSE inside a closure literal, and that difference
belongs to the site, never to two readings of the callee row.

WHAT U1 DELIBERATELY DOES NOT DO. A site the transform DECLINES today — a
callee or closure body the walk skipped and lowered as a plain call (SL-287,
SL-316) — is RECORDED with outcome `declined(reason)` and lowered exactly as
before. U1 is behaviour-preserving by construction; turning a decline into a
refusal is U2's flip and owes U2's consumer sweep. `--emit-frame-ledger` dumps
the list, which is what makes that worklist auditable instead of remembered.

ONE BOUNDARY WORTH NAMING, because the brief's wording invites the other
reading: the SITE table is a RECORD in U1, not a lookup key. Frame builders
REWRITE the bodies discovery walked — hoists, the ANF pass, binding
uniquification all mint fresh nodes — so a site row cannot be found again by
node identity once lowering starts, and keying it by (file, line, column) would
make a refusal depend on a position the transform itself moved. Consumers
therefore read the CALLEE table, which is the behavioural path today; the site
table is the dump, the decline worklist and U2's input, and U2's shape table is
what consults it BEFORE lowering, where node identity still holds.

THE DUMP IS A VALIDATION INSTRUMENT, and its stability is its whole value: it is
diffed between two compilers built from two checkouts, so it carries no absolute
path, no node id, no address and no set-iteration order. Frames sort by key;
sites sort by (file, line, column, callee, context, outcome). `file` is a
BASENAME for the same reason.
"""

from typing import NamedTuple, Optional

from frame_keys import callee_frame_key
from typechecker.effects import describe_causes


# --------------------------------------------------------------------------- #
# The row shapes
# --------------------------------------------------------------------------- #

# `FrameRow.kind` — what SHAPE of declaration this key names. The four are
# disjoint and exhaustive over what the transform builds a frame for.
KIND_FREE = "free"                    # a free function
KIND_METHOD = "method"                # an instance method (`&self`/`&var self`)
KIND_STATIC = "static"                # a static method — no receiver to embed
KIND_MONO = "mono-instance"           # a monomorphized clone of a generic

# `FrameRow.decision` — the THREE-VALUED answer. Absence of a row is NOT a
# fourth value: it is an invariant failure at every read that can tell the
# difference (see `FrameLedger.free_call_frame`).
DECISION_FRAMED = "framed"
DECISION_NO_FRAME = "no-frame-owed"
DECISION_DECLINED = "declined"

# `FrameRow.splice` — where the BODY the frame is built from came from.
ORIGIN_ENTRY = "entry"                # the entry module's own AST
ORIGIN_IMPORTED = "imported"          # spliced out of a dependency (SL-208)
ORIGIN_MONO = "mono"                  # adopted from the instantiation registry

# `SiteRow.context` — the position a suspension is reached from. The first three
# are the roles a FRAME plays; the last three are bodies the transform either
# refuses a suspension in or never frames at all. `sync body` and `Thread body`
# carry no rows today: both refusals are the typechecker's (design 242 ruling 9
# and the ordinary `sync` check), and they are named here because U2's shape
# table quantifies over the whole set and a context with no rows must be
# visible as such rather than absent.
CONTEXT_DRIVEN_ROOT = "driven root"
CONTEXT_EMBEDDED = "embedded"
CONTEXT_SPAWNED = "spawned"
CONTEXT_CLOSURE_BODY = "closure body"
CONTEXT_SYNC_BODY = "sync body"
CONTEXT_THREAD_BODY = "Thread body"

CONTEXTS = (CONTEXT_DRIVEN_ROOT, CONTEXT_EMBEDDED, CONTEXT_SPAWNED,
            CONTEXT_CLOSURE_BODY, CONTEXT_SYNC_BODY, CONTEXT_THREAD_BODY)


class FrameRow(NamedTuple):
    """One callee's frame decision, made once.

    `key` is the frame key — `frame_keys.callee_frame_key`'s answer for a free
    function, `method_frame_key`'s for a method — and it is what `__Frame_<key>`
    is named after, what an effect edge carries, and what a call site resolves
    against.

    `causes` is the design-275-U4 cause SET the effect graph reaches this node
    by, spelled (`{cooperative, closure_call}`). `boundary` is the FRAMING
    answer the transform acted on. The two can legitimately disagree in ONE
    direction and it is worth seeing: a std method's body belongs to a different
    typechecker, so it has no node in this graph and its cause set reads `{}`
    while its framing answer comes from the seeded census. A `boundary=yes` row
    with `causes={}` is that; a `boundary=yes` row with a NON-empty set that
    `frame_boundary` would read as no is a finding.

    `decision` is the THREE-VALUED answer, and it is what makes the ledger
    CLOSED (codex's P1 on SL-318.p4 r1). Before it, absence carried the negative:
    a key with no row and a key with a recorded "no frame owed" were the same
    fact to a consumer, so an UNDISCOVERED callee was indistinguishable from a
    discovered non-suspending one — which is the silent decline this epic exists
    to end, restated one level up.

      * `framed`        — a frame was built for this callee; embed it.
      * `no-frame-owed` — discovery looked and this callee owns no suspension a
                          frame must be built around. A plain call is CORRECT.
      * `declined`      — discovery looked, a suspension IS owed, and no frame
                          was built. `reason` says why. The transform lowers a
                          plain call, exactly as it did before U1; U2 flips
                          these and this column is its worklist.

    `buildable` is the brief's column, now derived from the decision: `yes` for
    `framed` and `no-frame-owed`, `no` with `reason` for `declined`.

    `causes` is the design-275-U4 cause SET the effect graph reaches this node
    by, spelled (`{cooperative, closure_call}`). `boundary` is the FRAMING
    answer the transform acted on. The two can legitimately disagree in ONE
    direction and it is worth seeing: a std method's body belongs to a different
    typechecker, so it has no node in this graph and its cause set reads `{}`
    while its framing answer comes from the seeded census. A `boundary=yes` row
    with `causes={}` is that; a `boundary=yes` row with a NON-empty set that
    `frame_boundary` would read as no is a finding.
    """
    key: str
    kind: str
    causes: str
    boundary: bool
    decision: str
    buildable: bool
    reason: Optional[str]
    home_module: str
    splice: str


class SiteRow(NamedTuple):
    """One call site's decision, in the context that site sits in.

    `outcome` is one of:

      * `embed`             — the callee's frame is embedded and driven here.
      * `inline`            — a suspension with no callee frame: a suspend
                              primitive, a channel receive, a blocking-extern
                              offload. Lowered into THIS frame.
      * `refuse(<why>)`     — a compile error the transform raises at this site.
      * `declined(<why>)`   — a suspension the transform lowers as a PLAIN CALL.
                              This is the outcome design 275 exists to end; U1
                              records it and changes nothing, U2 flips it.
    """
    file: str
    line: int
    column: int
    callee: str
    context: str
    outcome: str


# --------------------------------------------------------------------------- #
# Home module
# --------------------------------------------------------------------------- #

# The suffixes a mangled key can carry AFTER its module tag: design 55's
# overload signature, design 142's cross-module tie-break, and the
# instantiation arity marker `$<n>$`. Everything up to the first of them is the
# module.
_TAG_SUFFIXES = ("$OL$", "$LB$", "$M$")


def home_module_of(key, source_file=None):
    """WHICH MODULE this frame's declaration belongs to, for the dump.

    Read off the KEY when the key carries a module tag (design 249's `$m$` /
    design 142's `$M$`, which SL-274 made unconditional for every free function
    outside std) — the entry module's tag is deliberately EMPTY, so it renders
    as `<entry>`. A METHOD key carries no tag, so it falls back to the
    BASENAME of the file its declaration was written in; a basename rather than
    a path because this string is diffed between two checkouts.
    """
    if key:
        for tag in ("$m$", "$M$"):
            i = key.rfind(tag)
            if i < 0:
                continue
            rest = key[i + len(tag):]
            cut = len(rest)
            for sep in _TAG_SUFFIXES:
                j = rest.find(sep)
                if j >= 0:
                    cut = min(cut, j)
            # An instantiation marker is `$<digits>$`; find the first one.
            k = rest.find("$")
            if k >= 0:
                cut = min(cut, k)
            return rest[:cut] or "<entry>"
    if source_file:
        base = str(source_file).replace("\\", "/").rsplit("/", 1)[-1]
        return base[:-4] if base.endswith(".saw") else base
    return "-"


def basename_of(path):
    """The dump's `file` column: a basename, never a path (see the header)."""
    if not path:
        return "?"
    base = str(path).replace("\\", "/").rsplit("/", 1)[-1]
    return base or "?"


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

DUMP_VERSION = 1


def render_dump(frames, sites):
    """The `--emit-frame-ledger` text: both tables, deterministically ordered.

    Sorted here rather than by the caller, so the ORDER is a property of the
    format and no producer can emit a differently-ordered dump that still
    parses. Frames by key; sites by every column, left to right.
    """
    out = [f"# frame-ledger {DUMP_VERSION}"]
    rows = sorted(frames, key=lambda r: r.key)
    out.append(f"# frames: {len(rows)}")
    for r in rows:
        buildable = "yes" if r.buildable else f"no({r.reason or 'unknown'})"
        out.append(
            f"FRAME {r.key}\tkind={r.kind}\tcauses={r.causes}"
            f"\tboundary={'yes' if r.boundary else 'no'}"
            f"\tdecision={r.decision}"
            f"\tbuildable={buildable}"
            f"\thome={r.home_module}\tsplice={r.splice}")
    srows = sorted(sites, key=lambda r: (r.file, r.line, r.column, r.callee,
                                         r.context, r.outcome))
    out.append(f"# sites: {len(srows)}")
    for r in srows:
        out.append(
            f"SITE {r.file}:{r.line}:{r.column}\tcallee={r.callee}"
            f"\tcontext={r.context}\toutcome={r.outcome}")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# The capture the flag reads
# --------------------------------------------------------------------------- #
#
# `transform_program` runs deep inside `_prepare_codegen`, and it is the only
# place that holds the discovery state, so the dump is produced there and picked
# up here. A module-level capture rather than a threaded-through parameter
# because the flag is a DEVTOOL: nothing in the compile depends on it, and a
# parameter would put an analysis-only switch through every layer between the
# CLI and the transform.

_CAPTURE = False
_DUMP = None


def set_capture(on):
    """Turn the dump capture on (`--emit-frame-ledger`). Resets any held text."""
    global _CAPTURE, _DUMP
    _CAPTURE = bool(on)
    _DUMP = None


def capture_enabled():
    return _CAPTURE


def record_dump(text):
    """Called by the transform once discovery has finished and frozen."""
    global _DUMP
    if _CAPTURE:
        _DUMP = text


def take_dump():
    """The captured text, or an EMPTY ledger when the transform never ran.

    A program with no driven root never enters `transform_program`, and "no
    frames" is a real answer the dump has to be able to state — an absent file
    would make every such program a diff of one side against nothing.
    """
    if _DUMP is None:
        return render_dump([], [])
    return _DUMP


# --------------------------------------------------------------------------- #
# The method frame key, and what a method call site resolves to
# --------------------------------------------------------------------------- #

class LedgerMiss(Exception):
    """A consumer asked the ledger for a frame it holds no row for.

    An INVARIANT FAILURE, never a soft answer (design 275 U1's construction
    contract). The whole point of the ledger is that "I have no row for this
    key" and "this callee does not suspend" are different facts: before U1 they
    were one, because a table miss answered False, and a discovery gap was
    therefore indistinguishable from a correct negative — which is how a park
    came to be lowered through codegen's out-of-frame fallback and stop the
    cooperative executor's own thread on one idle socket (K102). `sawc.py`
    catches it beside `CoroTransformError` and reports it through `_report_ice`,
    so it reads as design 192 unit 2's ordinary internal-compiler-error line with
    the key in it — never a Python traceback, and never a plain call.
    """


def method_frame_key(struct_name, method_name, resolved_symbol=None):
    """Canonical frame key for a driven/embedded suspending METHOD (design 95).

    THE one spot that decides a driven-method frame's identity, and — with
    `frame_keys.callee_frame_key`, the free-function twin — one of the ledger's
    two COMPOSERS. Both are called from HERE and nowhere else: a consumer asks
    the ledger for a key, so a site cannot compose one of its own, which is
    SL-280's whole mechanism removed rather than patched.

    Two OVERLOADS of the same method name must get DISTINCT frames, so an
    overloaded suspending method is keyed by its design-55 resolved signature —
    the overload-mangled symbol (`Struct_write$OL$String`, carrying the
    `$OL$`/`$LB$` suffix) already composed by the typechecker: `mangled_symbol`
    on the method AST (definition side), `resolved_symbol` on the MethodCall
    (call site). A NON-overloaded method has no resolved symbol and keeps the
    plain `{struct}_{method}` key, so the common case (one signature per name) is
    byte-for-byte unchanged.

    A method key and a free-function key are DISJOINT spaces on purpose: a method
    is keyed by its owner and its signature, never by a free function's name.
    """
    return resolved_symbol or f"{struct_name}_{method_name}"


class MethodTarget(NamedTuple):
    """The answer `FrameLedger.method_target` gives. THREE values, not two."""
    kind: str                      # 'embed' | 'unsupported' | 'none'
    frame_key: Optional[str]       # 'embed' only — the frame this call embeds
    owner: Optional[str]           # the type the method belongs to, when known
    is_static: bool
    reason: Optional[str]          # 'unsupported' only — why it cannot be named

    @property
    def is_suspension(self):
        """Does this call SUSPEND? True for both answers that are not 'none' —
        an inexpressible suspending call is still a suspending call, and that
        is the whole of the bug this type exists to close.

        NOT spelled `suspends`: that is what an effect NODE's answer is called,
        and `corodiscovery` bans reading one outside the ledger's builder. Two
        different questions should not share a word at the site that asks."""
        return self.kind != 'none'


NOT_SUSPENDING = MethodTarget('none', None, None, False, None)


# --------------------------------------------------------------------------- #
# The ledger
# --------------------------------------------------------------------------- #

class FrameLedger:
    """THE closed frame table, and the ONE read API over it.

    Built by `coro_transform._build_frame_ledger` — a WORKLIST to stabilization,
    because an imported body or a generic instance can reveal further callees and
    a monomorphized clone of an imported generic is keyable only once its
    instantiation is known. "One pass" means one AUTHORITATIVE ANALYSIS, not one
    traversal. Discovery FINISHES before any body is lowered and the ledger is
    then FROZEN; a write afterwards is an invariant failure, and so is a MISS at
    a consumer.

    READ API — ENTRY POINTS (obligation 1: a funnel names its entries). The
    census below is the whole list; anything not here reads the ledger for
    nothing, and nothing anywhere else reads a raw input.

    | consumer | what it read before | what it reads now |
    |---|---|---|
    | `_FrameBuilder.__init__` | `callee_frame_key(func)` / `_method_frame_key(struct, name, func.mangled_symbol)` | `key_of` / `method_key_of_decl` |
    | `_FrameBuilder._is_suspension_point` | `callee_frame_key(expr) in self._suspends` | `free_call_frame` |
    | `_FrameBuilder._spans_suspension` | the same membership test | `free_call_frame` |
    | `_FrameBuilder._classify_call` | the same, plus the `callee` it emits | `free_call_frame` |
    | `_FrameBuilder._classify_method_call` | `callee_frame_key(mc) in self._suspends` + `_suspending_method_target` | `free_call_frame` + `method_target` |
    | `_FrameBuilder._module_free_call_suspends` | `callee_frame_key(mc) in self._suspends` | `free_call_frame` |
    | `_FrameBuilder._method_call_suspends` | `_suspending_method_target(mc, tc)` | `method_target` |
    | `_FrameBuilder._suspending_method_call` | the same | `method_target` |
    | `_FrameBuilder._reject_suspending_method_call` | the same | `method_target` |
    | `_FrameBuilder._reject_buried_suspend_call` | the membership test, `n.module_free_call`, `_suspending_method_target` | `free_call_frame`, `key_of`, `method_target` |
    | `_FrameBuilder._callee_fb` | `self._fbs[info['callee']]` | unchanged — `info['callee']` IS a ledger key now |
    | `_default_expr_suspends` | `nodes[("fn", callee_frame_key(n))].suspends` + `_suspending_method_target` | `might_suspend_free` + `method_target` |
    | `_find_suspending_cycle` | `node.edges` + `t.suspends` | `suspending_edge_targets` |
    | `_analyze_nesting` | `_node_display` + the caller's `is_built` closure | `node_label` + `is_built` |
    | `_promote_nested_generic_calls` | its OWN `classify_suspensions` walk, `callee_frame_key(fc)`, `f.name`/`is_mono_instance` over the merged AST | `instantiation_is_boundary`, `key_of`, `mono_free_bodies`, `rename_call_to`, `register_free_body` |
    | `_promote_nested_generic_methods` | `susp_methods`/`own_susp_methods` sets, `_method_frame_key(..., clone.mangled_symbol)`, `mc.coro_frame_key`, `funcs_by_name.get(callee_frame_key(fc))` | `method_might_suspend`/`method_owns_suspension`, `method_key_of_decl`, `method_frame_key_stamped`/`stamp_method_frame_key`, `free_body_of_call` |
    | `_scan_method_callees` (builder) | `_suspending_method_target` + `methods_by_key` | `method_target` + `method_id_for_key` |
    | `_structurally_suspends` (builder) | `funcs_by_name` then `imported_free_fns` | `free_or_imported_body` |
    | `_rewrite_drive_sites` | `_method_frame_key(..., inner.resolved_symbol)` / `callee_frame_key(inner)` | `method_key_of_call` / `key_of` |
    | `transform_program` dual-role scan | `callee_frame_key(_fc)` | `key_of` |
    | `transform_program` `nested_method_fbs` + method roots | `_method_frame_key(sname, mast.name, mast.mangled_symbol)`, `_find_method` | `method_key_of_decl`, `find_entry_method` |
    | `transform_program` splice filter | `callee_frame_key(f)` over `program.functions` | `key_of` |
    | the consumption sweep (`_called_function_names`, `_consume_templates_naming_removed`, `_names_the_survivors_call`) | `callee_frame_key` at four sites | `key_of` |

    `callee_frame_key`'s sixteen named entry points collapse to ONE caller — this
    class — and `method_frame_key`'s likewise. That collapse is the unit.

    WHICH READS ARE CHECKED, and which take ABSENCE as the answer. Every read
    above had to be decided one way or the other, because a read that answers
    "no" by absence cannot tell a decided negative from a discovery gap — which
    is exactly what codex's SL-318.p4 r1 review found still true of the first
    draft. The verdict per read, restated in each docstring:

    | read | absence means |
    |---|---|
    | `free_call_frame` | CHECKED. A recorded `framed` / `no-frame-owed` / `declined` answers; no row for a callee that OWNS a suspension is a `LedgerMiss` naming the key. Absence is the answer only for what is not a frame question: a genuine method call, an extern, a builtin, a synthesized call, a generic template |
    | `method_target` (EMBED) | CHECKED once frozen: an EMBED names a frame key, and the site census records a decision for every method call in every body that will be lowered, so a key with none is a gap. NOT SUSPENDING and UNSUPPORTED own no row and need none |
    | `frame` | CHECKED, always — the explicit strict lookup |
    | `is_built` | ABSENCE IS THE ANSWER. The suspending-call graph is wider than the frames; `_analyze_nesting` asks it precisely to find the nodes nothing built (SL-227's gate) |
    | `might_suspend_free` | ABSENCE IS THE ANSWER. A GRAPH read: no node means no suspension source |
    | `instantiation_is_boundary` | ABSENCE IS THE ANSWER, and it is asked before the freeze. An instance the registry never built has no node, and `no` sends the call to ordinary monomorphization |
    | `free_body` / `free_or_imported_body` / `importable_body` | ABSENCE IS THE ANSWER: "this unit holds no such free-function body" is a fact, not a gap |
    | `method_id_for_key` / `method_entry_for_key` | ABSENCE IS THE ANSWER at the table, and the census turns it into a recorded `declined` where it matters |
    """

    __slots__ = (
        "_answers", "_nodes", "_typechecker",
        "free_bodies", "imported_free_bodies", "spliced_keys",
        "mono_free_bodies", "mono_method_bodies",
        "methods_by_id", "_methods_by_key", "mono_recv_types",
        "_might_methods", "_own_methods",
        "closure", "method_closure", "_built_free", "_built_method_keys",
        "_root_method_ids", "method_root_decls", "_structural",
        "_frames", "_sites", "_frozen", "main_suspends",
    )

    # ---------------------------------------------------------------- lifecycle

    def __init__(self, answers, nodes, typechecker):
        self._answers = answers
        self._nodes = nodes if nodes is not None else {}
        self._typechecker = typechecker
        # THE BODY TABLES. `free_bodies` is the entry module's, plus whatever the
        # walk spliced or adopted into it; `imported_free_bodies` is the
        # importable set a splice draws from. Two tables and one key space — the
        # thing SL-280 found keyed two ways.
        self.free_bodies = {}
        self.imported_free_bodies = {}
        self.spliced_keys = set()
        # Phase 2's monomorphized instances, by mangled name / symbol — what the
        # two promotions ADOPT from rather than build a second producer of.
        self.mono_free_bodies = {}
        self.mono_method_bodies = {}
        # The method tables. `methods_by_id` is keyed by `Method.node_id` (what
        # an effect edge to a method carries); `_methods_by_key` by frame key.
        self.methods_by_id = {}
        self._methods_by_key = {}
        # design 223: a promoted generic-struct instantiation's CONCRETE receiver
        # type, the one thing its frame builder needs that a plain method's does
        # not.
        self.mono_recv_types = {}
        # The two method censuses. BROAD (`might_suspend`) decides whether a call
        # site is a suspension at all; OWN (`frame_boundary`) decides whether it
        # has a park to host, which is SL-306's distinction.
        self._might_methods = set()
        self._own_methods = set()
        # The discovery RESULT: the frames about to be built.
        self.closure = []                 # free-function keys, in walk order
        self.method_closure = {}          # method node_id -> (owner, ast, ext)
        self._built_free = set()
        self._built_method_keys = set()
        self._root_method_ids = set()
        # A driven METHOD ROOT's declaration, by frame key. Separate from
        # `methods_by_id` ON PURPOSE: the closure walk follows a method edge iff
        # its target is in `methods_by_id`, and a root resolved AFTER the walk
        # must not widen what the walk would have reached. Filled once discovery
        # has stabilized, so the SITE census can walk a root's body — codex's P2
        # on SL-318.p4 r1, which found every suspension in a driven method root
        # missing from the dump while its FRAME row was present.
        self.method_root_decls = {}     # frame_key -> (owner, decl, ext, recv)
        # The structural-suspension answers discovery computed (design 96's
        # route, which the effect graph cannot see). Handed over at the freeze so
        # a checked READ can ask the same question the walk asked.
        self._structural = {}
        # The two tables the dump renders and U2 consumes.
        self._frames = {}
        self._sites = []
        self._frozen = False
        # design 45 item 1: does this program's `main` suspend (and therefore get
        # wrapped in the entry executor)? A discovery FACT — it decides whether
        # `main` is a root — so it lives here rather than being recomputed from
        # the typechecker beside every use of it.
        self.main_suspends = False

    def freeze(self, structural=None):
        """Discovery is over. Every later touch is a READ.

        `structural` is the design-96 structural-suspension cache the walk
        built — a body whose only suspension is a buried std method call or a
        channel receive has no cause in the effect graph, and a checked read has
        to be able to ask the same question the walk asked, or it would call an
        undiscovered suspending callee "no suspension owed" on exactly the route
        SL-280's wedge came in by.
        """
        if structural:
            self._structural = dict(structural)
        self._frozen = True

    def _open(self, what):
        if self._frozen:
            raise LedgerMiss(
                f"the coroutine discovery ledger is "
                f"frozen and {what} was attempted after it — discovery must "
                f"finish before any body is lowered (design 275 U1)")

    # ------------------------------------------------------------- registration
    # Builder-side writers. Each one READS the raw inputs so that nothing else
    # has to: a caller hands over a declaration and gets a key back.

    def register_free_body(self, decl, origin=ORIGIN_ENTRY, key=None):
        """File a free-function body under its frame key; answer the key.

        `origin` records where the body came from, which is what the dump's
        `splice` column reports and what the emission invariant rests on: an
        IMPORTED clone is filtered back out of `program.functions` once its
        frame exists, because the imported module owns that symbol.
        """
        self._open("a free body registration")
        k = key if key is not None else callee_frame_key(decl)
        self.free_bodies[k] = decl
        if origin == ORIGIN_IMPORTED:
            self.spliced_keys.add(k)
        return k

    def register_imported_free_body(self, decl):
        """Offer an importable body. An ENTRY body of the same KEY wins, and a
        second offer of one key does not displace the first — the shadow-out
        SL-280 had to fix, comparing keys rather than written names so an entry
        `helper` no longer hides a dependency's tagged `helper$m$dep`."""
        self._open("an imported body registration")
        k = callee_frame_key(decl)
        if k not in self.free_bodies and k not in self.imported_free_bodies:
            self.imported_free_bodies[k] = decl
        return k

    def register_mono_free_bodies(self, decls):
        """Phase 2's monomorphized free instances, by mangled NAME."""
        self._open("a mono-instance registration")
        for d in decls or ():
            if getattr(d, 'is_mono_instance', False):
                self.mono_free_bodies.setdefault(getattr(d, 'name', None), d)

    def register_mono_method_bodies(self, extensions):
        """Phase 2's monomorphized method instances, by mangled SYMBOL."""
        self._open("a mono-method registration")
        for ext in extensions or ():
            for m in getattr(ext, 'methods', None) or ():
                sym = getattr(m, 'mangled_symbol', None)
                if sym and getattr(m, 'is_mono_instance', False):
                    self.mono_method_bodies.setdefault(sym, (m, ext))

    def register_method(self, owner, decl, ext):
        """File a method under BOTH keys an edge and a call site name it by —
        its `node_id` and its frame key — and answer the frame key."""
        self._open("a method registration")
        self.methods_by_id[decl.node_id] = (owner, decl, ext)
        k = self.method_key_of_decl(owner, getattr(decl, 'name', None), decl)
        self._methods_by_key[k] = decl.node_id
        return k

    def register_mono_method(self, key, owner, decl, ext, recv_type):
        """design 223: a promoted GENERIC-STRUCT instantiation sits in no
        `ext.methods` list, so the ordinary registration cannot see it. File it
        under the key its call sites were STAMPED with, and remember the concrete
        receiver type its frame's `__recv` must point at."""
        self._open("a mono-method registration")
        self.methods_by_id[decl.node_id] = (owner, decl, ext)
        self._methods_by_key[key] = decl.node_id
        self.mono_recv_types[key] = recv_type

    def note_method_census(self, owner, name, might, own):
        """Record what the effect graph says about one (owner, method) pair."""
        self._open("a method census update")
        if might:
            self._might_methods.add((owner, name))
        if own:
            self._own_methods.add((owner, name))

    def seed_method_census(self, might_pairs, own_pairs):
        """Seed the two censuses from the BUILTIN compile's own answers. A std
        method's body belongs to a different typechecker, so it has no node in
        this graph and the local loop can never judge one — without the seed,
        `TcpStream.read` and `JsonValue._write` are indistinguishable here."""
        self._open("a method census seed")
        self._might_methods.update(might_pairs or ())
        self._own_methods.update(own_pairs or ())

    def drop_method_from_broad_census(self, pair):
        """DF-206d: a method's OWN effect answer outranks a name that agrees with
        std's, so a std-seeded pair every local declaration says `no` about
        leaves the broad census."""
        self._open("a method census correction")
        self._might_methods.discard(pair)

    def add_built_free(self, key):
        self._open("a closure addition")
        self.closure.append(key)
        self._built_free.add(key)

    def add_built_method(self, node_id, owner, decl, ext, key):
        self._open("a method-closure addition")
        self.method_closure[node_id] = (owner, decl, ext)
        self._built_method_keys.add(key)

    def note_method_root_built(self, node_id, key):
        """A driven method ROOT is a frame by definition: `method_roots` is what
        builds it, so it is not in `method_closure`, which holds the CALLEES the
        walk reached. Without this half a self-recursive driven method fell back
        to the phase-2 frame-key ICE the cycle check exists to replace — which is
        why `is_built` has to answer for a ROOT id as well as a closure one."""
        self._open("a method-root note")
        self._root_method_ids.add(node_id)
        self._built_method_keys.add(key)

    def method_root_ids(self):
        """The node ids of the driven method ROOTS, for the cycle-check seeding."""
        return self._root_method_ids

    def register_method_root(self, key, owner, decl, ext, recv_type=None):
        """Record a driven METHOD ROOT's declaration for the site census.

        Deliberately NOT a `register_method`: that fills `methods_by_id`, which
        is what the closure walk follows a method edge into, and a root resolved
        after the walk must not change what the walk would have reached. This
        adds the key to the BUILT set (a root is a frame by definition) and the
        declaration to a table only the census and the dump read.
        """
        self._open("a method-root declaration")
        self.method_root_decls[key] = (owner, decl, ext, recv_type)
        self._built_method_keys.add(key)

    def record_frame(self, row):
        self._open("a frame row")
        self._frames.setdefault(row.key, row)

    def has_frame_row(self, key):
        return key in self._frames

    def record_site(self, row):
        self._open("a site row")
        self._sites.append(row)

    # ------------------------------------------------------------ the composers

    def key_of(self, node, name=None):
        """THE frame key the node `node` names, or None.

        The ledger's free-function COMPOSER — `frame_keys.callee_frame_key`
        wrapped, and the only place it is called. A declaration, a call site, a
        module-qualified free call wearing a `MethodCall`'s shape, and a
        namespace symbol all produce the same string, so a program where a
        callee carries a module tag behaves exactly as one where it does not.
        That independence is SL-280's fix and this is where it lives.
        """
        return callee_frame_key(node, name)

    def method_key(self, owner, method_name, resolved_symbol=None):
        """The ledger's METHOD composer (`method_frame_key`), likewise sole."""
        return method_frame_key(owner, method_name, resolved_symbol)

    def method_key_of_decl(self, owner, method_name, decl):
        """The frame key a method DECLARATION names — the definition side, whose
        overload symbol rides `mangled_symbol`."""
        return method_frame_key(owner, method_name,
                                getattr(decl, 'mangled_symbol', None))

    def method_key_of_call(self, owner, mc):
        """The frame key a method CALL names — the call side, whose overload
        symbol rides `resolved_symbol`."""
        return method_frame_key(owner, mc.method_name,
                                getattr(mc, 'resolved_symbol', None))

    # ------------------------------------------------------------ callee facts

    def free_call_frame(self, node):
        """The BUILT free-function frame key this call site embeds, or None.

        A CHECKED READ (codex's P1 on SL-318.p4 r1). It replaced
        `callee_frame_key(node) in self._suspends` at five classifier sites, and
        that membership test turned a table miss into `None` — the same answer a
        genuinely non-suspending callee gets. So an UNDISCOVERED suspending
        callee and a decided one were one fact, which is the silent decline this
        epic exists to end, one level up from where it was found.

        Three recorded answers and one refusal:

          * `framed`        -> the key, and the caller embeds the frame;
          * `no-frame-owed` -> None. Discovery LOOKED and this callee owns no
                               suspension; a plain call is correct;
          * `declined`      -> None, unchanged from before U1. The decision and
                               its reason are in the dump, and the flip is U2's;
          * NO ROW          -> `LedgerMiss` naming the key, IF the ledger can
                               tell the callee owns a suspension.

        ABSENCE IS A LEGITIMATE ANSWER exactly when the callee is not a frame
        question at all: a genuine METHOD call (`callee_frame_key` answers None —
        that is `method_target`'s question), an `extern`, a builtin, a
        synthesized call the transform itself minted, a std free function with
        no body in this unit, and a generic TEMPLATE, which owns no frame by
        construction. Everything else that OWNS a suspension and has no recorded
        decision is a discovery gap, and a gap must never read as "does not
        suspend".
        """
        key = callee_frame_key(node)
        if key is None:
            return None
        row = self._frames.get(key)
        if row is not None:
            return key if row.decision == DECISION_FRAMED else None
        if self._owns_a_suspension_unrecorded(key):
            raise LedgerMiss(
                f"the coroutine discovery ledger has no decision for the "
                f"suspending callee `{key}`, which a body being lowered calls. "
                f"Every callee that owns a suspension is decided about before "
                f"any body is lowered — framed, or declined with a reason — so "
                f"an absent row is a discovery gap, never `does not suspend` "
                f"(design 275 U1)")
        return None

    def _owns_a_suspension_unrecorded(self, key):
        """Would an absent decision for `key` be a GAP rather than an answer?

        Asked of the SAME two questions the closure walk asked, which is what
        makes this an invariant rather than a heuristic: the design-275-U4
        `frame_boundary` derivation, and design 96's STRUCTURAL route (a body
        whose only suspension is a buried std method call or a channel receive,
        which the effect graph cannot see and which the walk therefore probes
        separately). Two arms:

          * a body this unit HOLDS — the ordinary case. A generic TEMPLATE is
            excluded: it owns no frame by construction, its suspending
            instantiations are keyed separately, and a call still naming one is
            `_classify_call`'s clean design-70 refusal, not an ICE.
          * NO body anywhere, but a graph node that says BOUNDARY. Still a gap:
            had the walk reached that key it would have raised `suspending
            function `{key}` not found in the entry module`, so a consumer
            meeting it means discovery never got there.

        AN EMPTY LEDGER HOLDS NO INFORMATION and therefore answers False to
        everything — there is no body table, no graph and no cause set to ask.
        The invariant is over a ledger discovery actually built; the regression
        that proves it lives in `tools/test_coro_discovery.py`, which drops a row
        from a REAL compile and requires the named-key ICE.
        """
        body = self.free_or_imported_body(key)
        if body is not None:
            if getattr(body, 'type_params', None):
                return False
            if self._answers.frame_boundary(("fn", key)):
                return True
            return bool(self._structural.get(key, False))
        return bool(self.has_graph_node(("fn", key))
                    and self._answers.frame_boundary(("fn", key)))

    def is_built(self, key):
        """Does a frame exist for `key`? Takes either key space, and the graph
        spelling `("fn", name)` the cycle walk carries.

        ABSENCE IS THE ANSWER here, and deliberately: `_analyze_nesting` asks it
        of every node on a suspending-call CYCLE, and the suspending-call graph
        is WIDER than the set of frames the transform builds. A node the walk
        declined to reach is exactly what this has to answer `no` for — that is
        the gate SL-227 added so a cycle through an un-embedded callee is not
        refused (blade's own resolver was that program). A miss here is not a
        gap; it is the question."""
        if isinstance(key, tuple) and len(key) == 2 and key[0] == "fn":
            return key[1] in self._built_free
        if isinstance(key, int):
            return key in self.method_closure or key in self._root_method_ids
        return key in self._built_free or key in self._built_method_keys

    def frame(self, key):
        """The recorded decision for `key`. A MISS IS AN INVARIANT FAILURE.

        Never permission to emit a plain call — the silent decline this epic
        exists to end. `sawc.py` renders the raised `LedgerMiss` as an internal
        compiler error naming the key, so a discovery gap is a located compiler
        bug rather than a wedged program.
        """
        row = self._frames.get(key)
        if row is None:
            raise LedgerMiss(
                f"the coroutine discovery ledger has "
                f"no frame decision for `{key}` — every callee a consumer asks "
                f"about is discovered before lowering (design 275 U1)")
        return row

    def might_suspend_free(self, key):
        """The BROAD answer for a free function: any suspension cause at all.

        What `_default_expr_suspends` and `_find_suspending_cycle` want — the
        first because a defaulted argument naming a callee the transform LOWERS
        cannot be copied whatever the cause, the second because a cycle is
        narrowed afterwards by `is_built`. SL-324 records that the first of those
        two probably wants the FRAMING answer instead; the flip is U2's, and
        recording it here rather than changing it is what keeps U1
        behaviour-preserving.

        ABSENCE IS THE ANSWER: this is a GRAPH read, not a table read. A key with
        no effect node reaches no suspension source, which is exactly what `no`
        means here — a defaulted argument naming an `extern` or a builtin has no
        node and needs none, and a cycle walk that ICE'd on one would refuse
        every program.
        """
        return bool(key) and self._answers.might_suspend(("fn", key))

    def free_boundary(self, key, structural_probe=None):
        """Does this free callee own a suspension a FRAME has to be built around?

        `frame_boundary` over the design-275-U4 cause set, OR — design 96 — the
        STRUCTURAL route the graph cannot see: a body whose only suspension is a
        buried std method call or a channel receive, whose callee has no node in
        this graph at all. Builder-side and the dump's `boundary` column.
        """
        if not key:
            return False
        if self._answers.frame_boundary(("fn", key)):
            return True
        return bool(structural_probe is not None and structural_probe(key))

    def edge_is_boundary(self, target, structural_probe=None):
        """The closure walk's edge-follow question, over a GRAPH key."""
        if self._answers.frame_boundary(target):
            return True
        if (structural_probe is not None and isinstance(target, tuple)
                and len(target) == 2 and target[0] == "fn"):
            return bool(structural_probe(target[1]))
        return False

    def instantiation_is_boundary(self, mangled):
        """Does this monomorphized instantiation OWN a suspension?

        The SAME question the closure walk's edge-follow and `method_target` ask
        (SL-306 review r1, codex P1), because promotion and framing are one
        decision seen from two ends: an instance that suspends only through the
        conservative closure-call cause is not promoted, both call sites stay
        plain calls, and codegen's ordinary monomorphization serves them. It read
        the broad bit once, and one instance was framed for a DIRECT driven call
        and left plain for a conservative-only caller — one body, rewritten into
        a resume state machine and then reached by a plain call.

        ABSENCE IS THE ANSWER, and it is builder-side besides: an instantiation
        the registry never built has no node, and `no` is what sends the call to
        codegen's ordinary monomorphization. Asked BEFORE the freeze, so there is
        no decision table to miss.
        """
        key = ("fn", mangled)
        return (key in self._nodes
                and self._answers.frame_boundary(key))

    def causes_of_free(self, key):
        return describe_causes(self._answers.causes(("fn", key)))

    def causes_of_node(self, node_id):
        return describe_causes(self._answers.causes(node_id))

    # ------------------------------------------------------------ method facts

    def method_might_suspend(self, owner, name):
        """The BROAD census: is a call to this method a suspension at all?"""
        return (owner, name) in self._might_methods

    def method_owns_suspension(self, owner, name):
        """The OWN census (SL-306): does this method have a park to host?"""
        return (owner, name) in self._own_methods

    def method_id_for_key(self, key):
        return self._methods_by_key.get(key)

    def method_entry_for_key(self, key):
        mid = self._methods_by_key.get(key)
        return self.methods_by_id.get(mid) if mid is not None else None

    def method_frame_key_stamped(self, mc):
        """The frame key generic promotion STAMPED on this call, or None."""
        return getattr(mc, 'coro_frame_key', None)

    def stamp_method_frame_key(self, mc, key):
        """Stamp it. The one writer, so a call site's key and the table's agree
        by construction rather than by two sites composing the same string."""
        self._open("a method frame-key stamp")
        mc.coro_frame_key = key

    def method_target(self, mc):
        """THE call-site classifier for a suspending METHOD call (design 223 u1).

        Three-valued, and the third value is the point:

          * EMBED(frame_key)      — a suspending method whose frame this call
                                    site can name and embed.
          * UNSUPPORTED(reason)   — a suspending method whose frame it CANNOT
                                    name. The caller's job is to RAISE. It must
                                    never degrade to a plain call: the callee's
                                    park would run outside any frame, where
                                    `yield_now` is a no-op, and the cooperative
                                    contract would be silently dropped on a
                                    program that compiles, runs and prints the
                                    right answer.
          * NOT_SUSPENDING        — not a suspending method call at all,
                                    INCLUDING a method that suspends only by the
                                    conservative closure-call rule (SL-306).
                                    Such a callee has no park of its own, so a
                                    plain call is the correct lowering and a
                                    frame around it is what was wrong.

        WHAT IT READS. An INSTANCE call carries its owner on the RECEIVER's
        resolved type — `struct_name` for a struct and `enum_name` for an ENUM
        (design 145 gave enums extensions, design 74 gives methods frames, and
        DF-218l is where the two had not met). A STATIC call has no receiver, so
        the typechecker stamps `static_receiver` on the call (DF-184a).

        A GENERIC receiver or a method-level generic needs an INSTANTIATION to be
        named at all, and the instantiation is not something a classifier can
        conjure — `_promote_nested_generic_methods` builds it during discovery and
        STAMPS the resulting frame key on the call. So a stamped call is EMBED
        whatever its type arguments look like, and an unstamped one whose
        receiver or call carries type arguments is UNSUPPORTED. That keeps ONE
        question here ("can I name this frame?") and leaves "can this frame be
        built?" to the building.

        CHECKED (codex's P1). An EMBED answer names a frame key, and once the
        ledger is frozen that key MUST have a recorded decision: the site census
        walks the same bodies the classifiers will and records one for every
        method call it meets, so a key with none after the freeze is a discovery
        gap. Absence is a legitimate answer for the other two kinds — NOT
        SUSPENDING names no frame at all, and UNSUPPORTED is a refusal whose
        whole point is that no frame could be named.
        """
        if getattr(mc, 'is_chan_recv', False):
            # design 62 G3: a cooperative `receive()` lowers INLINE — it suspends
            # and embeds nothing, so it is not this classifier's business.
            return NOT_SUSPENDING
        if not self._might_methods:
            return NOT_SUSPENDING
        is_static = bool(getattr(mc, 'is_static_method_call', False))
        if is_static:
            owner = getattr(mc, 'static_receiver', None)
            recv_args = getattr(mc.object, 'type_args', None)
        else:
            rt = getattr(mc.object, 'resolved_type', None)
            owner = ((getattr(rt, 'struct_name', None)
                      or getattr(rt, 'enum_name', None))
                     if rt is not None else None)
            recv_args = getattr(rt, 'type_args', None) if rt is not None else None
        stamped = self.method_frame_key_stamped(mc)
        if stamped is not None:
            return self._checked_embed(stamped, owner, is_static)
        if owner is None:
            # No compile-time owner: an existential receiver, a type parameter, a
            # primitive. Nothing here can name a frame, and nothing here KNOWS
            # whether one is owed — the existential case is DF-223b, refused by
            # the typechecker at the dispatch, where the trait is in hand.
            return NOT_SUSPENDING
        if not self.method_might_suspend(owner, mc.method_name):
            return NOT_SUSPENDING
        # SL-306: ONE question, asked once, for BOTH answers below. The broad
        # census holds `Vector.each`, `Map.each`, `JsonValue._write` and every
        # method that reaches one, which "suspend" solely by the rule that a call
        # through a non-`sync` function value might. A method that suspends no
        # other way has no park to host, so there is nothing for this call site
        # to embed OR to refuse — it lowers as the plain call it is, which is
        # what the callee's own body compiles to. The closure's OWN suspension,
        # if it has one, is still refused where it is written.
        if not self.method_owns_suspension(owner, mc.method_name):
            return NOT_SUSPENDING
        if recv_args or getattr(mc, 'type_args', None):
            # Un-nameable, and it owns a suspension: REFUSE, never degrade.
            if recv_args:
                return MethodTarget(
                    'unsupported', None, owner, is_static,
                    f"its receiver `{owner}<...>` is a generic instantiation "
                    f"this call site could not be monomorphized for")
            return MethodTarget(
                'unsupported', None, owner, is_static,
                f"it is a generic method (`{mc.method_name}<...>`) this call "
                f"site could not be monomorphized for")
        return self._checked_embed(self.method_key_of_call(owner, mc),
                                   owner, is_static)

    def _checked_embed(self, frame_key, owner, is_static):
        """An EMBED answer, with its recorded decision verified once frozen."""
        if self._frozen and frame_key not in self._frames:
            raise LedgerMiss(
                f"the coroutine discovery ledger has no decision for the "
                f"suspending method frame `{frame_key}`, which a call site "
                f"being lowered names. Every method call in every body the "
                f"transform lowers is decided about before lowering starts, so "
                f"an absent row is a discovery gap (design 275 U1)")
        return MethodTarget('embed', frame_key, owner, is_static, None)

    def find_entry_method(self, program, struct_name, method_name,
                          method_symbol=None):
        """Locate a driven method's AST and the extension that owns it.

        design 95: when the method name is overloaded, `method_symbol` (the
        resolved overload-mangled symbol) selects the exact overload — a
        name-only match would return whichever was declared first. On the ledger
        because that selection is a KEYING read, and keying reads are the
        ledger's.
        """
        for ext in program.extensions:
            if getattr(ext, 'struct_name', None) != struct_name:
                continue
            for m in ext.methods:
                if m.name != method_name:
                    continue
                if method_symbol is not None and \
                        getattr(m, 'mangled_symbol', None) != method_symbol:
                    continue
                return m, ext
        return None, None

    # ----------------------------------------------------------- body lookups

    def free_body(self, key):
        return self.free_bodies.get(key)

    def free_body_of_call(self, node):
        """The entry-table body the call `node` names, or None. `funcs_by_name`
        keyed by frame key, asked through the composer — reading a written name
        here stopped `_promote_nested_generic_methods` dead at any callee
        registration had stamped a symbol on."""
        return self.free_bodies.get(callee_frame_key(node))

    def free_or_imported_body(self, key):
        """Either body table, entry FIRST. A body not yet spliced still has to be
        able to answer the structural-suspension question — the phase ordering
        SL-280 closed."""
        body = self.free_bodies.get(key)
        return body if body is not None else self.imported_free_bodies.get(key)

    def importable_body(self, key):
        return self.imported_free_bodies.get(key)

    # -------------------------------------------------------------- call edits

    def rename_call_to(self, fc, mangled):
        """Point a generic call at its promoted INSTANTIATION.

        Three writes that must happen together, which is why they are one method:
        the written name becomes the instance, the TEMPLATE's stale
        `resolved_symbol` is cleared (or `key_of` would answer the base the
        instance was cloned from), and the type arguments go. SL-274 is what made
        the third necessary and the second load-bearing.
        """
        self._open("a call rename")
        fc.name = mangled
        fc.resolved_symbol = None
        fc.type_args = None

    # -------------------------------------------------------------- graph reads

    def suspending_edge_targets(self, key):
        """The graph keys `key` calls that THEMSELVES suspend — the edges
        `_find_suspending_cycle` follows. A cycle over these is *suspending*
        recursion, which the flat-frame (embed-by-value) model cannot size."""
        node = self._nodes.get(key)
        if node is None:
            return ()
        out = []
        for e in node.edges:
            t = self._nodes.get(e.target)
            if t is None or not self._answers.might_suspend(e.target):
                continue
            out.append(e.target)
        return out

    def has_graph_node(self, key):
        return key in self._nodes

    def graph_edge_targets(self, key):
        """Every edge out of `key`, suspension or not — the closure walk's own
        iteration, which asks `edge_is_boundary` per edge."""
        node = self._nodes.get(key)
        return () if node is None else tuple(e.target for e in node.edges)

    def node_label(self, key):
        """How a node names itself in a diagnostic (the cycle chain)."""
        n = self._nodes.get(key)
        if n is not None:
            return n.short.strip("`")
        if isinstance(key, tuple) and len(key) == 2:
            return key[1]
        return str(key)

    # -------------------------------------------------------------------- dump

    def dump(self):
        return render_dump(self._frames.values(), self._sites)

    def declined_sites(self):
        """U2's worklist: every site the transform lowers as a plain call."""
        return [r for r in self._sites if r.outcome.startswith("declined")]
