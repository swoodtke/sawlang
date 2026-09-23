"""THE STATEMENT-SCOPED WINDOW (design 275 U3).

A WINDOW is a borrow of a ROOT that lasts for the extent of ONE STATEMENT. It
is not a for-loop feature: `for` is its FIRST CLIENT, and the reuse obligation
(user, Sep 20) is that the generic scoped-borrow statement the follow-up brief
specifies adds its syntax, its typechecking client and its acquisition/result
binding — and NO second implementation of root accounting, pinning, suspension
persistence or exit cleanup.

WHY A RECORD AND NOT A RULE ON `ForLoop`. Three passes need the same four
facts, and each of them would otherwise re-derive them from the loop's shape:

  * the TYPECHECKER charges the root, refuses the writers, and accounts for
    the close on every route;
  * the COROUTINE TRANSFORM asks "is a window live across this suspension" and,
    when it is, mints the frame field, encodes the referent as a design-88
    pointer, and closes the window on every exit route out of the state
    machine;
  * CODEGEN lowers the sync form — the resource's slot, and the DROP-BEFORE-
    CHARGE-END order.

None of those three reads `ForLoop`. They read the RECORD, which is what makes
the second client a new `open_window` call rather than a second copy of all
three. (`tools/test_window_seam.py`, the `windowseam` battery lane, fails when
a `ForLoop` mention appears in this module or in the transform's window
handling outside the named adapter.)

THE FOUR BOUNDARIES (codex c44), which this module's API shape encodes:

  B1  ITERATION belongs to the client; WINDOW LIFETIME belongs here. The record
      holds a GENERIC resource slot (`resource_name`, `resource_type`), never a
      field named `__iter` nor an `Iterator`-shaped payload — the `for` client
      puts an iterator in it, a future accessor client would put a lend result.
      Not every `ForLoop` opens one: a RANGE loop and an OWNED-iterator loop
      open none and take the ordinary split.
  B2  A window closes by CONTROL-FLOW TARGET, not by the spelling of the exit.
      `windows_left_by` takes a RESOLVED target and answers which windows an
      edge leaves, inside-out. An implementation that special-cases `Continue`
      as "keep open" leaks the first client's shape; this one asks whether the
      target is inside or outside each extent.
  B3  The record has a LIFECYCLE — ACQUIRE, ACTIVE, RELEASE — and RELEASE runs
      a CLIENT-PROVIDED cleanup operation. For `for` that is "destroy the
      borrowing iterator"; an accessor window's would be an epilogue, and an
      optional head may take an `else` branch without ever activating a window,
      so nothing here assumes release is a drop or that every evaluated head
      opens a window.
  B4  The direct-head / temporary-receiver refusals apply to BORROWING results
      only. A window exists because a value CARRIES a borrow; a head that
      produces an owned value opens none.

THE MODES. `shared` is the only one U3 exercises; `exclusive` is reserved
rather than invented, because the derivation (writer-versus-reader, nested
windows) is the follow-up's to specify. The field is here so the follow-up
adds rows rather than a second record.
"""

from typing import Any, List, Optional, Tuple

#: The window modes. `shared` composes with other readers; `exclusive` excludes
#: everything. U3 opens shared windows only — see the module docstring.
SHARED = 'shared'
EXCLUSIVE = 'exclusive'
MODES = (SHARED, EXCLUSIVE)

#: The ORIGINS a window's borrow may have. U3 admits one, and the string is the
#: summary recorded on the producing declaration (`Method.borrow_origin`), so
#: the call site substitutes it onto the receiver place's root rather than
#: walking the body.
RECEIVER_ROOT = 'receiver root'
ORIGINS = (RECEIVER_ROOT,)


class StatementWindow:
    """ONE window: a root borrowed for the extent of one statement.

    DELIBERATELY NOT A DATACLASS, and this is load-bearing rather than style.
    The record is STAMPED ON THE STATEMENT (`ForLoop.window`), and
    `typechecker/effects.py:substitute_ast_types` — monomorphization's type
    rewrite — walks `dataclasses.fields()` rather than `structural_fields()`
    and recurses into every dataclass VALUE it finds. A dataclass record whose
    `extent` points back at the statement holding it is therefore a cycle, and
    the walk goes down it until the interpreter's recursion limit. A plain
    class is opaque to that walk, which is exactly the right answer: a window
    record carries no `SawType` for monomorphization to substitute.

    `extent` is the CHECKER's field. After the checker, `mono_copy` may clone
    the statement and the clone's record still names the ORIGINAL node — which
    costs nothing, because from the transform onward what is read is the root,
    the mode and the resource, never the identity of the extent.

    `root_path` is design 141's root attribution applied to the head's RECEIVER
    place — `v.iter()` charges `('v', ())`, `st.patches.iter()` charges
    `('st', ('patches',))`, an enclosing-owner path per design 8/10. It is what
    every conflict question compares, and it is a PATH rather than a name
    because a field path names a smaller thing than its owner and the Law
    already knows how to overlap the two.

    `extent` is the STATEMENT node the window lives for. Lexical, so every
    route out leaves it — which is the whole of "no route may leave the charge
    live past the statement".

    `resource_*` is B1's generic slot: the value that CARRIES the borrow, which
    the client initialized into persistent storage at ACQUIRE and which
    RELEASE destroys before the charge ends.
    """
    __slots__ = ('root_path', 'root_id', 'mode', 'origin', 'extent', 'client',
                 'line', 'column', 'resource_name', 'resource_type', 'state',
                 'reported')

    def __init__(self, root_path, root_id, mode, origin, extent, client,
                 line, column):
        self.root_path: Tuple[str, Tuple[str, ...]] = root_path
        self.root_id: Optional[int] = root_id
        self.mode: str = mode
        self.origin: str = origin
        self.extent: Any = extent       # the statement node that IS the extent
        self.client: str = client       # 'for' — supplies diagnostic wording
        self.line: int = line
        self.column: int = column
        # B1's generic resource slot — the borrowing value, its type, and the
        # name of the hidden binding it lives in (never nameable in source).
        self.resource_name: Optional[str] = None
        self.resource_type: Optional[Any] = None
        # B3: ACQUIRE -> ACTIVE -> RELEASE. A window is only `active` once the
        # resource is initialized into its slot; RELEASE never runs on an
        # uninitialized resource, which is what an optional head's `else` arm
        # needs and what a failing argument (A3) relies on.
        self.state: str = 'acquiring'
        # Lines already reported against, so one statement that reaches the
        # root several times yields one diagnostic (the `_task_borrows`
        # precedent).
        self.reported: set = set()

    @property
    def root_name(self) -> str:
        return self.root_path[0]

    def renders_root(self) -> str:
        """The root as an author would read it back.

        A path's projections are the Law of Exclusivity's own
        `('field', name)` / `('tuple', i)` / `('index', k)` triples
        (`_build_access_path`), so rendering is spelling them back rather than
        joining strings.
        """
        head, hops = self.root_path
        out = head
        for hop in hops or ():
            if not isinstance(hop, tuple) or len(hop) != 2:
                out += ".?"
            elif hop[0] == 'field':
                out += f".{hop[1]}"
            elif hop[0] == 'tuple':
                out += f".{hop[1]}"
            else:
                out += "[…]"
        return out


#: An array index that is not a compile-time constant. Compared by IDENTITY,
#: so it can never be equal to a real index value.
DYNAMIC_INDEX = object()


def paths_overlap(a: Tuple[str, Tuple[str, ...]],
                  b: Tuple[str, Tuple[str, ...]]) -> bool:
    """Do two access paths name storage that can be the same?

    THE ONE DEFINITION of the Law of Exclusivity's path algebra (obligation 1).
    It lives in this leaf module because BOTH readers reach it here and neither
    reaches the other: `typechecker/types.py:_paths_overlap` — the call-set,
    task-borrow and place-window question — delegates to it, and `WindowTable`
    asks it directly, because a window compares paths OUTSIDE any call.

    THE TABLE. Different roots are disjoint. On the same root the hop sequences
    are walked in parallel: different KINDS at one position, different field
    names, different tuple indices or different CONSTANT array indices are
    disjoint; a DYNAMIC index at a position overlaps whatever is there, because
    the value is not known until run time; and running out of hops on either
    side (one path a prefix of the other) is an overlap — `v` overlaps
    `v.items`, `p.a` and `p.b` do not.

    The dynamic-index row is the one a second implementation loses, and losing
    it is unsound rather than merely conservative: the window's own copy
    compared hops for EQUALITY, so `bins[i]` and `bins[0]` were judged disjoint
    and a `bins[0].push` ran inside a window over `bins[i]` with `i == 0`
    (codex r1 #3).
    """
    if a[0] != b[0]:
        return False
    for ha, hb in zip(a[1] or (), b[1] or ()):
        if not isinstance(ha, tuple) or not isinstance(hb, tuple):
            return True                     # an unreadable hop is conservative
        if ha[0] != hb[0]:
            return False
        if ha[0] == 'index':
            if ha[1] is DYNAMIC_INDEX or hb[1] is DYNAMIC_INDEX:
                continue
            if ha[1] != hb[1]:
                return False
        elif ha[1] != hb[1]:
            return False
    return True


class WindowTable:
    """THE ONE CHOKEPOINT every statement window is opened and closed through.

    CLIENTS (obligation 1 — a funnel names its entries). Each client calls
    `open_window` with its own root, mode, origin and extent, supplies its own
    RELEASE operation, and reads back nothing of its own shape:

      * `for` — `typechecker/borrowing.py:open_for_window` /
        `close_for_window`, called from `typechecker/statements.py`'s two
        `for` checkers. It supplies the head (a `borrows` producer call on a
        place) and the body, and its release operation destroys the borrowing
        iterator. THE ONLY CLIENT IN U3.

      * (reserved) the generic scoped-borrow STATEMENT the follow-up brief
        specifies — a keyword-introduced block binding a lent place, with an
        `else` arm for a `borrows -> &T?` head. It would call `open_window`
        with mode from its own spelling, an `else` arm that never reaches
        `activate`, and a release operation that runs the accessor epilogue.

    WHAT THE CHOKEPOINT DOES, so no client does it twice:
      * the ROOT CHARGE (`open_window` -> `conflict_for`, read at the four
        access sites the Law already has);
      * the EXCLUSIVITY conflicts, including a `&var` extent live at the head
        or STARTED inside the body;
      * the MOVE / REASSIGN / TAKE / SWAP refusals on the root and on every
        enclosing owner (K20's precedent, one message);
      * the CLOSE-ON-EVERY-ROUTE accounting, by RESOLVED control-flow target
        (`windows_left_by`).
    """

    def __init__(self):
        #: The open windows, OUTERMOST FIRST. LIFO: the innermost window is the
        #: last entry, which is what makes `windows_left_by` answer inside-out
        #: by walking the list backwards.
        self.open: List[StatementWindow] = []
        #: Every window this table ever opened, in open order — the transform
        #: and codegen read records off their extent nodes, but the ledger is
        #: what a dump and a gate lane enumerate.
        self.all: List[StatementWindow] = []

    # -- ACQUIRE / ACTIVE / RELEASE (B3) ---------------------------------

    def open_window(self, root_path, root_id, mode, origin, extent, client,
                    line, column) -> StatementWindow:
        """Open ONE window and make it the innermost. B3's ACQUIRE step A5.

        The caller has already run A1-A4 — resolved the receiver PLACE, opened
        the head's own shared borrow over the WHOLE call expression (arguments
        included), evaluated the arguments left to right, and run the producer.
        This is the HAND-OFF with no gap: the same root, the same mode, one
        continuous extent.
        """
        assert mode in MODES, mode
        assert origin in ORIGINS, origin
        w = StatementWindow(root_path=tuple(root_path), root_id=root_id,
                            mode=mode, origin=origin, extent=extent,
                            client=client, line=line, column=column)
        self.open.append(w)
        self.all.append(w)
        return w

    def activate(self, w: StatementWindow, resource_name, resource_type):
        """The resource is initialized into its persistent slot: ACTIVE.

        Separated from `open_window` because RELEASE must never run on an
        uninitialized resource — an optional head that takes its `else` arm,
        and a head whose argument failed (A3), both leave a window that was
        never activated and owes no cleanup.
        """
        w.resource_name = resource_name
        w.resource_type = resource_type
        w.state = 'active'
        return w

    def close_window(self, w: StatementWindow):
        """RELEASE. Exactly once, and only on a window that is open."""
        if w in self.open:
            self.open.remove(w)
        w.state = 'released'
        return w

    # -- B2: closing by CONTROL-FLOW TARGET ------------------------------

    def windows_left_by(self, target_extents) -> List[StatementWindow]:
        """The open windows an edge LEAVES, innermost first.

        `target_extents` is the set of extent nodes the edge's RESOLVED target
        is still inside — everything the edge does NOT leave. A window whose
        extent is in that set stays open; every other open window closes, and
        they close inside-out.

        This is B2 stated as one question rather than as a case per statement
        kind. `continue` targeting THIS loop passes the loop's own extent, so
        the window stays; `break` targeting it does not, so it closes;
        `break`/`continue` targeting an INNER loop passes every outer extent,
        so nothing of the outer closes; a window nested inside an outer loop
        closes when control continues that outer loop, because the outer loop's
        extent is in the set and the inner one is not; and `return`, an error
        propagation and a cancellation pass the EMPTY set, so every crossed
        scope closes.
        """
        keep = {id(e) for e in (target_extents or ())}
        return [w for w in reversed(self.open) if id(w.extent) not in keep]

    # -- the root charge, read by the Law's existing access sites ---------

    def conflict_for(self, root_path, writes: bool,
                     started_inside: bool = False,
                     root_id: Optional[int] = None) -> Optional[StatementWindow]:
        """The innermost open window an access to `root_path` collides with.

        IDENTITY FIRST, PROJECTIONS SECOND. A window borrows a BINDING; the
        path only carries the name it was spelled with. Where the caller can
        resolve the access's current binding and the window recorded its own,
        two different bindings never conflict however alike they read — which
        is what makes a legal refining shadow inside the body
        (`var v = v.copy()`) an independent root. Either side unknown falls
        through to the path comparison, which is the conservative answer.

        THE TABLE, which is the Law of Exclusivity read over a statement-length
        window rather than a call-length one:

          * a SHARED window composes with other readers and collides with a
            WRITE, a MOVE, a REASSIGN, a TAKE or a SWAP of the root or of any
            enclosing owner on its path;
          * an EXCLUSIVE window (reserved) collides with every touch.

        `started_inside` names an access that OPENS a new by-reference extent
        inside the body (a `&var` argument, a design-189 task capture): those
        conflict on the same table, and the flag exists only so the diagnostic
        can say which of the two the author wrote.
        """
        for w in reversed(self.open):
            if w.state == 'released':
                continue
            if (root_id is not None and w.root_id is not None
                    and root_id != w.root_id):
                continue                    # a different BINDING of one name
            if not paths_overlap(w.root_path, tuple(root_path)):
                continue
            if w.mode == EXCLUSIVE or writes:
                return w
        return None
