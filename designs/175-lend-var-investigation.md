# Design 175 — investigation: `#lend_var`, flavor-aware borrows bodies

**Status: INVESTIGATION APPROVED (user, Aug 7: "an investigation in the
#exclusive pattern would be useful"). Probe-only — the product is a
feasibility report + effort estimate; implementation is a follow-up decision.
NAMING (user, Aug 7): **`#lend_var`** — the spelling ties to the
nomenclature the language already uses for this exact pair: `&` vs `&var`
at every borrow site, and std's `with_ref`/`with_var_ref` long-window
twins. It is also MORE precise than intent-flavored names: the model is
permission-based (a `&var` argument opens an exclusive window whether or
not a write lands), and "this is a var-lend" states what is true.
Rejected: `#exclusive` (too abstract), `#lend_for_write`/`#borrow_for_write`
(intent-flavored — overpromise a write). Final confirmation rides the
report, but `#lend_var` is the working spelling throughout.
Queue: probe-only and concurrent-eligible; dispatch when a slot frees;
findings compose with 171's probe round (shared places surface).**

## The problem it solves

A `borrows` accessor has ONE body serving both window flavors, and the body
cannot see which is coming — but the COMPILER can: every use site's flavor is
static (a read = shared window, a write/`&var` = exclusive). DF-165c is the
cost: a CoW type must separate storage BEFORE lending a writable place, so
`Data.[]` declared `&var self` and gates unconditionally — and every pure
READ through `d[i]` now demands exclusivity. That broke three real read
sites in one afternoon (irdet's `same_bytes`, both serde169 encoders), each
written by an author reaching for the natural spelling.

## The mechanism (to be validated, not assumed)

A compile-time constant, legal ONLY inside a `borrows` body, in the
`#file`/`#line` magic-literal family:

```saw
public func [](&self, i: Int) borrows -> UInt8 {
    if #lend_var {                    // per-specialization constant
        self.separate_if_shared()     // the CoW gate — write copy only
    }
    if i >= self.length { panic("Data.[]: index out of range") }
    lend self.storage[self.offset + i]
}
```

The accessor compiles as TWO specializations (the const-generic precedent:
folded before mangling, branch statically pruned). The shared copy never
mutates and is honestly callable through `&self`/`let` roots; the write copy
runs the gate and takes the exclusive receiver it always needed. No caller
ceremony — the use site already carries the information.

## Probe matrix

1. **Checker architecture:** can mutation-legality be judged PER
   SPECIALIZATION (the false copy prunes the mutating branch BEFORE the
   `&self`-may-not-mutate check runs; the true copy gets `&var`-receiver
   semantics)? Where in the pass order would specialization have to happen,
   and does the design-146 "borrows changes what &self means" rule already
   carry half of this?
2. **Mangling + one-definition:** two symbols per flavored accessor (the
   `Dual_mix$2$T$U` precedent) — irdet/reemitdiff determinism, `--emit-docs`
   presentation (one accessor, note the flavors), frame layout if the
   accessor is reached from a coro context.
3. **Composition:** conditional lends (`borrows -> T?`) — does the absent
   path specialize too; epilogues per copy; LIFO window nesting; match-arm
   payload lends; a generic accessor with a flavored body; place borrows
   charging the root identically in both copies.
4. **The pilot on paper:** `Data.[]` rewritten under the mechanism — does
   `bytes[i]` on a `let`/`&Data` compile again, does the write path still
   gate, do the three formerly-broken sites compile as originally written,
   and does `get(i)` remain the explicit shared read (yes — the synonym
   ruling DF-146j is unaffected; `[]`-shared and `get` converge, which is
   the point).
5. **Scope fences:** `#lend_var` outside a borrows body = clean error;
   an accessor that never mentions it compiles ONCE exactly as today (no
   code-size tax on the unflavored majority); interaction with `&var self`-
   DECLARED accessors (always-true constant, or an error for redundancy?).
6. **Alternatives worth one paragraph each in the report:** the Swift-style
   two-body `_read`/`_modify` split (more declaration surface, no magic
   constant), and doing nothing (the `get`/`[]` pair as permanent idiom —
   what today's three breakages say about that).

## Deliverables

Report appended to this brief: feasibility verdict per probe, the
recommended spelling with the naming rationale restated, effort estimate,
and a go/no-go recommendation. DF-175x findings for anything the probes
trip over. NO compiler changes — prototypes under .build/scratch/ only.
