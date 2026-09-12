"""THE PRESERVATION AUDIT — does the program codegen receives still carry the
decision the checker made about it?

Design 270 (SL-212), unit C of the SL-209 ownership-uniformity epic.

THE PROBLEM THIS SOLVES. Unit A (design 267) made the checkpoint record an
explicit decision per transfer occurrence; unit B (design 269) made the producer
question total, so a decision is made at every boundary rather than the ones a
node-type list happened to cover. Both of those are facts about THE TREE THE
TYPECHECKER SAW. Between that tree and the one codegen consumes, four passes
rewrite bodies — and a decision keyed to an occurrence detaches the moment a
pass replaces the node it names. Unit D cannot retire codegen's second opinion
(`_transfer_needs_copy`) until the decision codegen would read is the decision
the checker made about the code that is actually there.

THE FOUR PASSES THIS AUDIT COVERS (obligation 1 — one chokepoint, run once on
the finished program, so a pass cannot bypass it by forgetting to call it):

  1. GENERIC SPECIALIZATION (`monomorphize.materialize_instance` over
     `mono_copy.substituting_copy`). A clone gets fresh `node_id`s, so it
     inherits no decision — and it is RE-CHECKED, so it files its own. Rule P3
     is the proof that the re-derivation happened and resolved the template's
     abstract answer rather than reusing it. Rule P1 is the fence on the other
     side: `_copy_node` copies `__dict__` wholesale, so a `needs_copy` stamp
     DOES ride onto every clone, and a clone that ever stopped being re-checked
     would carry the stamp with nothing behind it.
  2. CLOSURE CONVERSION. An ordinary closure's captures are synthesized
     `Identifier`s the checkpoint judges at entry point 16; the transform's own
     capture materialization is pass 4's second family. P1 covers both.
  3. PLACE LOWERING (`place_uses.transform_place_uses`). Runs before the
     transform and again over its output, each time followed by a re-check, so
     every lowered node is judged afterwards. P1 is the fence.
  4. THE COROUTINE TRANSFORM. The pass with the real holes, all three measured:
     it MOVES a transfer to a different site (which is why this audit keys on
     identity and never on position — the transform synthesizes whole frame
     bodies at line 0 column 0, where every synthesized node collides with
     every other), it CHANGES the action at a site it keeps, and a frame read
     DEFERS to a settlement that used to be reachable by nothing. Rules P2 and
     P4 are the fences.

WHAT IT DOES NOT DO. It does not run before codegen by default — that is unit E
(SL-214), the mandatory pre-codegen verifier, and this module is the engine it
will promote. Here it is driven by `tools/test_transfer_decisions.py` (the
`transferdecisions` battery lane) over a fixture corpus, and by
`SAW_TRANSFER_AUDIT=1` on every compile, which is how the whole `examples/`
corpus is swept.

THE FAILURE MODE THIS MODULE IS BUILT AGAINST (the SL-212 review, obligation 4).
An audit rule that takes its obligations FROM the thing it is checking cannot
see that thing removed: deleting the obligation deletes the check, and the loss
certifies clean. Both blockers on revision 1 were that shape, and the sweep
found a third. Every rule is therefore classified by what defines its subject,
and each one that could be emptied is paired with a rule driven from the other
side:

  * P1 reads the ANNOTATIONS -> P1r reads the LEDGER's `lowering` record.
  * P1a reads instances with no surviving decision, and P3 reads surviving
    decisions -> P1b reads the NODES of cloned bodies.
  * P1b and P3 read `origin_node_id` -> P5 checks the origin universe itself,
    against the one fact that makes it knowable: `mono_copy` copies a template's
    body WHOLE, so every node of an instance carries the stamp (99.1% measured;
    the remainder is exactly the auto-wrap family, which the instance CHECK
    inserts after the clone exists).
  * P4 reads `discharge` -> clearing one makes P2 fire, since a `deferred`
    decision with no discharge is P2's own violation.

ONE RESIDUAL IS NAMED RATHER THAN PAPERED OVER: deleting the decision for an
UNSTAMPED transfer at a NON-cloned node is not detected. P1b covers the cloned
case and P1r the stamped case; what is left has no independent oracle, because
"is this position a transfer?" is answered by the checkpoint's entry-point list
and duplicating that list here is the shape obligation 1 exists to refuse. Unit
E (SL-214) closes it by construction — a verifier that RUNS the checkpoint
enumerates the boundaries instead of guessing them — and this module is the
engine it promotes.

SCOPE, STATED RATHER THAN ASSUMED. std's own bodies are type-checked once,
under a separate builtin typechecker, and pickled into the std cache — so on a
cache hit the ledger is empty for them while their stamps survive the pickle.
Design 267 recorded that as a scope limit and it is one here too: a declaration
is IN SCOPE when the ledger holds at least one decision inside it, which is
self-calibrating and reported, rather than a hard-coded path list that would go
stale. Out-of-scope bodies are COUNTED in the summary so the limit is visible
instead of silent.
"""

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

from ast_nodes import (ErasedErrWrap, Extension, Function, Method, OptionalWrap,
                       ResultErrWrap, ResultOkWrap)
from ast_walk import child_nodes

from . import ownership


@dataclass(frozen=True)
class Finding:
    """One violated preservation property."""
    rule: str            # P1 | P2 | P3 | P4
    message: str
    where: str = ''

    def __str__(self) -> str:
        return f"{self.rule}: {self.message}" + (f"  [{self.where}]"
                                                 if self.where else "")


@dataclass
class AuditReport:
    findings: List[Finding]
    #: Counters, for the summary line and for the non-vacuity argument: a lane
    #: that checks nothing passes just as quietly as one that checks everything,
    #: so the numbers are printed.
    counts: Dict[str, int]

    @property
    def ok(self) -> bool:
        return not self.findings


# ---------------------------------------------------------------------------
# Walking the FINISHED program.
# ---------------------------------------------------------------------------

def structural_walk(root) -> List:
    """Every node STRUCTURALLY under `root`.

    A walk over `__dict__` is the wrong instrument here and getting it wrong was
    the first thing this audit had to fix: `resolved_symbol` and friends are
    back-pointers that reach declarations which are NOT in the program, so a
    generic template counts as emitted and a monomorphized clone's stamps look
    orphaned when they are not. `child_nodes` follows structural fields only,
    which is exactly "the program tree".
    """
    out, seen, stack = [], set(), [root]
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        out.append(node)
        stack.extend(child_nodes(node))
    return out


def _template_methods(program) -> Set[int]:
    """`id()` of every method that belongs to a GENERIC extension.

    A method of `extension Held<T>` carries no `type_params` of its own but is
    still a template; only the extension knows. Missing this would have made
    every std generic's methods look like emitted bodies with unresolved
    deferrals.
    """
    out: Set[int] = set()
    for ext in (getattr(program, 'extensions', None) or []):
        if not isinstance(ext, Extension) or not getattr(ext, 'type_params', None):
            continue
        for m in (getattr(ext, 'methods', None) or []):
            if not getattr(m, 'is_mono_instance', False):
                out.add(id(m))
    return out


def _is_emitted(decl, template_methods: Set[int]) -> bool:
    """Is this a body codegen will actually lower?

    A generic TEMPLATE is not: it exists to be cloned, its transfers are judged
    abstractly on purpose, and a `specialization:` deferral is the right answer
    there. Every other body is emitted, and an unresolved deferral in one is a
    transfer nothing answered.
    """
    if getattr(decl, 'is_mono_instance', False):
        return True
    if getattr(decl, 'type_params', None):
        return False
    return id(decl) not in template_methods


def _declaration_owners(program) -> Tuple[Dict[int, object], Set[int]]:
    """node_id -> the Function/Method whose body structurally holds it."""
    owner: Dict[int, object] = {}
    templates = _template_methods(program)
    for decl in structural_walk(program):
        if not isinstance(decl, (Function, Method)):
            continue
        for node in structural_walk(decl):
            nid = getattr(node, 'node_id', None)
            if nid is not None:
                owner.setdefault(nid, decl)
    return owner, templates


def _name(decl) -> str:
    if decl is None:
        return '<no owner>'
    src = getattr(decl, 'source_file', None)
    return (f"{os.path.basename(src) if src else '?'}:"
            f"{getattr(decl, 'line', 0)} {getattr(decl, 'name', '?')}")


# ---------------------------------------------------------------------------
# THE AUDIT.
# ---------------------------------------------------------------------------

def audit_preservation(program, decisions: Sequence,
                       obligations: Optional[Dict[int, str]] = None
                       ) -> AuditReport:
    """THE funnel. The properties below, over the finished program and the
    ledger.

    `program` is the merged AST handed to `run_codegen`; `decisions` is every
    `TransferDecision` this compile filed (`TypeChecker.transfer_decisions()`,
    from every checker instance that contributed); `obligations` is
    `TypeChecker.retain_obligations()` from the same instances, merged — the
    retain each node still owes, recorded where it was stamped rather than read
    back off the annotation it is an obligation ABOUT.
    """
    findings: List[Finding] = []
    obligations = dict(obligations or {})
    nodes = structural_walk(program)
    live_ids = {n.node_id for n in nodes
                if getattr(n, 'node_id', None) is not None}
    owner, templates = _declaration_owners(program)

    # Every decision, indexed by the SOURCE NODE it judged — which is what an
    # antecedent names. A node has one boundary and so usually one decision;
    # more than one means the front half reached it under two contexts, and all
    # of them answer for "was this node ever judged".
    by_node: Dict[int, List] = {}
    live_by_node: Dict[int, List] = {}
    for d in decisions:
        nid = d.key[0]
        if nid is None:
            continue
        by_node.setdefault(nid, []).append(d)
        if nid in live_ids:
            live_by_node.setdefault(nid, []).append(d)

    # SCOPE. A declaration is in scope when THIS ledger holds a decision inside
    # it — per DECLARATION, never per file. std's own bodies are checked under a
    # separate builtin typechecker and pickled into the std cache, so on a cache
    # hit their stamps survive and their decisions are in another ledger (or in
    # none); a file-level rule pulled those in and reported 15 of 20 stamps as
    # detached when nothing was.
    #
    # A MONO INSTANCE IS ALWAYS IN SCOPE, and that exception is what keeps the
    # rule from being vacuous: the instance is a clone THIS compile made, so
    # this compile is the only thing that could have judged it. Without the
    # carve-out, a pass that stopped checking instances would remove every
    # decision from a clone and thereby remove the clone from scope — the audit
    # would go quiet on exactly the failure it exists for. Probed: disabling the
    # instance check makes P1 fire five times.
    decided_decls = {id(owner[nid]) for nid in by_node
                     if nid in owner and owner[nid] is not None}
    out_of_scope = 0

    def in_scope(decl) -> bool:
        if decl is None:
            return False
        return (id(decl) in decided_decls
                or bool(getattr(decl, 'is_mono_instance', False)))

    counts = {k: 0 for k in ('nodes', 'decisions', 'live', 'stamps',
                             'stamps_checked', 'deferred_live',
                             'deferred_emitted', 'antecedents',
                             'resolutions', 'coro_rewrites', 'instances',
                             'lowerings', 'cloned_occurrences',
                             'origin_stamps', 'out_of_scope')}
    counts['nodes'] = len(nodes)
    counts['decisions'] = len(decisions)
    counts['live'] = sum(len(v) for v in live_by_node.values())

    # ---- P1a: AN INSTANCE WHOSE TEMPLATE WAS JUDGED IS JUDGED TOO --------
    # The scope rule's other half, and the rule that survives a pass which
    # removes every decision from a clone — the failure the other rules go quiet
    # on, because a body with no decisions has nothing for them to look at.
    #
    # THE TEMPLATE IS THE ORACLE, not "does this body have transfers". Asking
    # the second question would mean enumerating boundaries a second time, which
    # is the duplicate-rule shape obligation 1 exists to refuse; and answering
    # it by "any body with statements" is wrong — `Atomic.store` and a
    # synthesized `deinit` genuinely have no transfer in them, and reported as
    # violations. `origin_node_id` already says which nodes the clone came from,
    # so the honest question is: did the TEMPLATE's corresponding nodes carry
    # decisions? If they did and the clone's carry none, the clone was
    # materialized and never judged.
    for decl in nodes:
        if not isinstance(decl, (Function, Method)):
            continue
        if not getattr(decl, 'is_mono_instance', False):
            continue
        counts['instances'] += 1
        if id(decl) in decided_decls:
            continue
        judged_origins = [n for n in structural_walk(decl)
                          if getattr(n, 'origin_node_id', None) in by_node]
        if not judged_origins:
            continue                      # the template had nothing here either
        findings.append(Finding(
            'P1', f"a monomorphized instance body carries NO transfer decision, "
                  f"while the template it was cloned from carries "
                  f"{len(judged_origins)} — this compile materialized the "
                  f"instance and never judged it", _name(decl)))

    # ---- P1b: EVERY CLONED OCCURRENCE, NOT EVERY CLONED BODY -------------
    # THE SL-212 REVIEW'S P1. P1a asks whether an instance body has ANY decision
    # and P3 iterates the decisions that SURVIVED, so losing ONE occurrence's
    # record inside an otherwise-decided instance was invisible — measured: all
    # records for a single live `NoneLiteral` in a monomorphized `init` were
    # removed (action `take`, destination `struct field`, origin still
    # template-decided, siblings intact) and the audit returned zero findings.
    #
    # Both of those rules take their obligations from the surviving decisions,
    # which is the same shape as P1's: the input set defines the obligation, so
    # deleting the obligation deletes the check. This one is driven by the
    # NODES instead. A node the copier produced carries `origin_node_id`; if the
    # node it descends from was judged, then this node is an occurrence the
    # front half was supposed to re-derive, and its decision must exist.
    # TWO DISCRIMINATORS ARE NEEDED, and both are measured rather than guessed.
    # `deepcopy` has a second caller: the coroutine transform, which duplicates
    # judged nodes into positions that are NOT transfers (a receiver copied for
    # a synthesized `cancelled()` probe, an optional-chain spine) and re-parents
    # them into frame bodies it wrote. Those clones legitimately carry no
    # decision of their own, and requiring one reported V94's `resume` on
    # unmodified source.
    #
    #   * A TRANSFORM-SYNTHESIZED declaration is excluded. Inside a frame the
    #     transform is the authority by construction, and that is already
    #     fenced, by name, through the `coro-frame-rewrite` /
    #     `coro-frame-synthesis` discharges and P2/P4.
    #   * An INTRA-BODY duplication is excluded. `mono_copy` copies a TEMPLATE's
    #     body into an INSTANCE's, so a specialization clone's origin lives in a
    #     DIFFERENT declaration; a transform duplicating a node it already holds
    #     leaves both in one.
    #
    # What remains is the body-to-body clone this rule is about, and neither
    # exclusion needs a list of node types or a second enumeration of what
    # counts as a transfer position.
    for node in nodes:
        nid = getattr(node, 'node_id', None)
        origin = getattr(node, 'origin_node_id', None)
        if nid is None or origin is None or origin not in by_node:
            continue
        decl = owner.get(nid)
        if not in_scope(decl) or decl is None:
            continue
        if not _is_emitted(decl, templates):
            continue
        if getattr(decl, 'is_synthesized', False):
            continue                      # a coroutine frame; see P2/P4
        origin_decl = owner.get(origin)
        if origin_decl is not None and origin_decl is decl:
            continue                      # an intra-body duplication, not a clone
        counts['cloned_occurrences'] += 1
        if nid in by_node:
            continue
        findings.append(Finding(
            'P1b', f"a cloned {type(node).__name__} whose origin WAS judged "
                   f"({sorted({p.action for p in by_node[origin]})} at "
                   f"`{by_node[origin][0].destination}`) carries no decision of "
                   f"its own — the re-derivation this occurrence needed did not "
                   f"happen, or its record was lost", _name(decl)))

    # ---- P1: STAMP/DECISION RECONCILIATION, FORWARD ----------------------
    # The two things a transfer leaves behind — the ANNOTATION codegen reads and
    # the DECISION the ledger holds — must agree node for node in the program
    # handed to codegen. This direction catches a clone inheriting a stamp
    # without inheriting a judgment. It reads the ANNOTATION as its input, so it
    # can only ever see obligations that are still stamped; P1r below is the
    # other direction and is the one that survives a cleared stamp.
    for attr, want in (('needs_copy', ownership.ACTION_COPY),
                       ('payload_needs_copy', None)):
        for node in nodes:
            if not getattr(node, attr, False):
                continue
            decl = owner.get(getattr(node, 'node_id', None))
            if not in_scope(decl):
                out_of_scope += 1
                continue
            counts['stamps'] += 1
            found = live_by_node.get(node.node_id)
            # BACKED BY A DECISION *OR* BY A RECORDED OBLIGATION. Design 267
            # says the payload rule is a SEPARATE funnel that files no
            # decisions, and that is load-bearing here: an `o!` and a `try` sit
            # at boundaries the checkpoint judges, but an `if let`, a
            # `guard let` and a `??` stamp a node the checkpoint never sees as a
            # transfer source. Demanding a decision for those reported V99's
            # `guard_let` on correct code. What makes a stamp SOUND is that some
            # pass of this compile put it there, and the obligation table is the
            # record of exactly that — while a clone that merely INHERITED the
            # annotation through `__dict__` has neither, which is the case this
            # rule exists for.
            if not found and node.node_id not in obligations:
                findings.append(Finding(
                    'P1', f"`{attr}` is stamped on a "
                          f"{type(node).__name__} that NO live decision and no "
                          f"recorded obligation covers — codegen will act on a "
                          f"judgment nothing in this compile made",
                    _name(decl)))
                continue
            counts['stamps_checked'] += 1
            if not found:
                continue                  # a payload-funnel stamp; P1r owns it
            if want is not None and not any(d.action == want for d in found):
                findings.append(Finding(
                    'P1', f"`{attr}` is stamped but the decisions for that "
                          f"occurrence say {sorted({d.action for d in found})} "
                          f"— the stamp and the judgment disagree",
                    _name(decl)))

    # ---- P1r: THE SAME RECONCILIATION, FROM THE LEDGER ------------------
    # THE SL-212 REVIEW'S P2. P1 takes its obligations FROM the annotations, so
    # clearing one deletes the obligation from the audit's own input and the
    # loss certifies clean — measured: clearing a single `payload_needs_copy`
    # on a `try` left the audit green while the emitted program stopped
    # performing the checker's copy (`got 7` with no `copy 7`).
    #
    # The fix is to read the obligation off the LEDGER, which the erasure cannot
    # reach: a decision records the annotation it observed (`lowering`), and
    # this checks that the annotation is still there. PER OBLIGATION and BY
    # NAME, because the two stamps are different obligations at different nodes
    # and an aggregate count cannot tell one dropped retain from none.
    # THE OBLIGATION TABLE IS THE INPUT, not the decisions and not the
    # annotations. Revision 2 read this off `TransferDecision.lowering`, which
    # only the final implicit-copy arm populates — so the DELEGATED payload
    # read (`_check_payload_read` stamps `payload_needs_copy` on an `o!`, the
    # checkpoint files `delegated`/`payload-read`) carried no obligation and
    # clearing its stamp dropped a real retain under a green audit. That was the
    # third patch the one mechanism would have taken, so the obligation now
    # comes from `_stamp_retain`, the single writer every producer routes
    # through, and covers each face of design 131's family alike.
    #
    # `TransferDecision.lowering` stays as the decision-side echo for the arms
    # that have a decision — unit D reads a decision, not this table — and is
    # cross-checked below rather than trusted as the enumeration.
    node_by_id = {n.node_id: n for n in nodes
                  if getattr(n, 'node_id', None) is not None}
    for nid, attribute in sorted(obligations.items()):
        node = node_by_id.get(nid)
        if node is None:
            continue                      # a pass dropped the node entirely
        decl = owner.get(nid)
        if not in_scope(decl):
            continue
        counts['lowerings'] += 1
        if not getattr(node, attribute, False):
            findings.append(Finding(
                'P1r', f"the checker stamped `{attribute}` on this "
                       f"{type(node).__name__} and the program handed to "
                       f"codegen does not carry it — the retain will not be "
                       f"performed", _name(decl)))

    # The decision-side echo must agree with the table wherever it is set, or
    # the two records of one obligation have drifted. THE OPERATIVE DECISION
    # only: a pass that MOVES an expression leaves the node with decisions under
    # two boundaries — the coroutine transform turns a `try` bound by a `let`
    # into a call argument — and only the later is the program's judgment.
    for nid, ds in live_by_node.items():
        decl = owner.get(nid)
        if not in_scope(decl):
            continue
        d = max(ds, key=lambda x: x.sequence)
        if not d.lowering:
            continue
        if obligations.get(nid) != d.lowering:
            findings.append(Finding(
                'P1r', f"a `{d.action}` decision at `{d.destination}` records "
                       f"`{d.lowering}` as its lowering, and the obligation "
                       f"table says {obligations.get(nid)!r} — the two records "
                       f"of one retain disagree", _name(decl)))

    # ---- P2: NO UNEXPLAINED DEFERRAL IN AN EMITTED BODY -----------------
    # `deferred` is a hand-off, and a hand-off that names nobody is
    # indistinguishable from a boundary nothing judged — the exact distinction
    # design 267 built the ledger to make.
    for nid, ds in live_by_node.items():
        decl = owner.get(nid)
        if not in_scope(decl):
            continue
        emitted = _is_emitted(decl, templates) if decl is not None else True
        for d in ds:
            if d.action != ownership.ACTION_DEFERRED:
                continue
            counts['deferred_live'] += 1
            kind = ownership.discharge_kind(d.discharge)
            if kind is None:
                findings.append(Finding(
                    'P2', f"a `deferred` decision at `{d.destination}` names no "
                          f"discharge — nothing says where its answer lives",
                    _name(decl)))
                continue
            if kind not in ownership.DISCHARGES:
                findings.append(Finding(
                    'P2', f"a `deferred` decision at `{d.destination}` carries "
                          f"discharge `{d.discharge}`, which is not one of "
                          f"{sorted(ownership.DISCHARGES)}", _name(decl)))
                continue
            if not emitted:
                continue
            counts['deferred_emitted'] += 1
            if kind == ownership.DISCHARGE_SPECIALIZATION:
                findings.append(Finding(
                    'P2', f"an EMITTED body carries the TEMPLATE's abstract "
                          f"deferral ({d.discharge}) at `{d.destination}` — the "
                          f"instance reused the template's answer instead of "
                          f"deriving its own", _name(decl)))

    # ---- P3: SPECIALIZATION RESOLVES ------------------------------------
    # A clone's decision must be its own. Where its antecedent could not answer,
    # the descendant must; where the antecedent DID answer, the two must agree
    # unless a later pass had authority to change it and said so.
    for nid, ds in live_by_node.items():
        decl = owner.get(nid)
        if not in_scope(decl):
            continue
        for d in ds:
            if d.antecedent is None:
                continue
            counts['antecedents'] += 1
            parents = by_node.get(d.antecedent)
            if not parents:
                continue          # the antecedent's own body was never checked
            # Prefer the parent judged at the SAME boundary; a transform that
            # reuses an author's node at a boundary of its own making has none,
            # and then every judgment of that node answers.
            same = [p for p in parents if p.destination == d.destination]
            candidates = same or parents

            def _is_spec_deferral(dec):
                return (dec.action == ownership.ACTION_DEFERRED
                        and ownership.discharge_kind(dec.discharge)
                        == ownership.DISCHARGE_SPECIALIZATION)

            if all(_is_spec_deferral(p) for p in candidates):
                if _is_spec_deferral(d):
                    findings.append(Finding(
                        'P3', f"a clone at `{d.destination}` inherited its "
                              f"template's abstract deferral instead of "
                              f"resolving it", _name(decl)))
                else:
                    counts['resolutions'] += 1
                continue
            if (d.discharge
                    or any(p.action == d.action for p in candidates)):
                continue
            findings.append(Finding(
                'P3', f"a clone at `{d.destination}` decided `{d.action}` where "
                      f"the node it descends from decided "
                      f"{sorted({p.action for p in candidates})}, and names no "
                      f"discharge for the change", _name(decl)))

    # ---- P4: THE DEFERRAL CHAIN GROUNDS OUT ------------------------------
    # The coroutine transform's frame read defers to "the pre-transform tree
    # judged this". P4 checks that the settlement it names is a REAL ANSWER and
    # not another hand-off: a chain of deferrals that never reaches a judgment
    # leaves codegen with nothing to honour, which is the same hole one level
    # deeper. `deferred` and `none` are not answers; every other action is.
    answered = {ownership.ACTION_TAKE, ownership.ACTION_COPY,
                ownership.ACTION_MOVE, ownership.ACTION_BORROW,
                ownership.ACTION_REFUSED, ownership.ACTION_DELEGATED}
    for nid, ds in live_by_node.items():
        decl = owner.get(nid)
        if not in_scope(decl):
            continue
        for d in ds:
            if (ownership.discharge_kind(d.discharge)
                    != ownership.DISCHARGE_CORO_REWRITE):
                continue
            counts['coro_rewrites'] += 1
            if d.antecedent is None:
                findings.append(Finding(
                    'P4', f"a `coro-frame-rewrite` deferral at "
                          f"`{d.destination}` carries no antecedent — the "
                          f"discharge claims a pre-transform judgment and "
                          f"names none", _name(decl)))
                continue
            parents = by_node.get(d.antecedent) or []
            if not parents:
                findings.append(Finding(
                    'P4', f"a `coro-frame-rewrite` deferral at "
                          f"`{d.destination}` names an antecedent the ledger "
                          f"does not hold — the settlement it defers to never "
                          f"happened", _name(decl)))
            elif not any(p.action in answered for p in parents):
                findings.append(Finding(
                    'P4', f"a `coro-frame-rewrite` deferral at "
                          f"`{d.destination}` defers to a node whose own "
                          f"decisions are all hand-offs "
                          f"({sorted({p.action for p in parents})}) — the "
                          f"chain never reaches an answer codegen can honour",
                    _name(decl)))

    # ---- P5: THE ORIGIN UNIVERSE IS NOT SHRINKABLE ----------------------
    # THE THIRD INSTANCE of the mechanism the SL-212 review named. P1b and P3
    # both take their subject from `origin_node_id`, so clearing one would
    # remove an occurrence from the audit's universe rather than fail a check —
    # the same shape as taking obligations from a stamp or from a surviving
    # decision, one level further out.
    #
    # It is fenceable because the universe is knowable: `mono_copy` copies a
    # template's body WHOLE, so every node of an instance body came from the
    # copier and must carry the stamp. Measured at 99.1% on two fixtures, and
    # the 0.9% is not noise — it is exactly the auto-wrap family, which the
    # INSTANCE CHECK inserts after the clone exists (the return/tail ladder), so
    # those nodes were never in the template and correctly carry nothing.
    synthesized_by_check = (OptionalWrap, ResultOkWrap, ResultErrWrap,
                            ErasedErrWrap)
    for decl in nodes:
        if not isinstance(decl, (Function, Method)):
            continue
        if not getattr(decl, 'is_mono_instance', False):
            continue
        if not in_scope(decl):
            continue
        for node in structural_walk(decl):
            if node is decl or isinstance(node, synthesized_by_check):
                continue
            if getattr(node, 'node_id', None) is None:
                continue
            counts['origin_stamps'] += 1
            if getattr(node, 'origin_node_id', None) is None:
                findings.append(Finding(
                    'P5', f"a {type(node).__name__} inside a monomorphized "
                          f"instance body carries no `origin_node_id` — the "
                          f"copier stamps every node it produces, so this "
                          f"occurrence has dropped out of the universe P1b and "
                          f"P3 reconcile", _name(decl)))
                break         # one report per body is enough to locate it

    counts['out_of_scope'] = out_of_scope
    return AuditReport(findings=findings, counts=counts)


def summary(report: AuditReport) -> str:
    c = report.counts
    return (f"preservation audit: {c['nodes']} program nodes, "
            f"{c['decisions']} decisions ({c['live']} live); "
            f"{c['stamps_checked']}/{c['stamps']} stamps reconciled; "
            f"{c['deferred_live']} live deferrals "
            f"({c['deferred_emitted']} in emitted bodies); "
            f"{c['antecedents']} antecedent links, "
            f"{c['resolutions']} specialization resolutions, "
            f"{c['coro_rewrites']} coro rewrites, "
            f"{c['instances']} instance bodies, "
            f"{c['cloned_occurrences']} cloned occurrences, "
            f"{c['lowerings']} lowering obligations, "
            f"{c['origin_stamps']} origin stamps; "
            f"{c['out_of_scope']} stamps out of scope")
