# Design 104 — coro embedding: if-let/guard-let bodies + the remaining generic shapes (queued Aug 2)

Final pre-SOS batch, part 3 of 6. Lift the remaining clean-error
embedding limits in the coroutine transform.

## Item 1 — suspending method calls in `if let` / `guard let` bodies (design-101 residue)
Currently rejected cleanly (the design-101 fix made the silent-block
impossible; embedding needs CFG-splitting the optional-binding
branches). Implement the split: desugar/split the if-let (and guard-
let) into the transform's state machine the same way
`_hoist_suspending_conditions`/`_split_match` handle if/match — the
bound name becomes a frame field (design 101 already added
`_pattern_binding_names` for match; reuse). Keep the design-100
shadowing rule's `if let x = x` semantics intact across the split.
Tests: suspending read/write inside if-let and guard-let bodies in a
driven loop round-trip (recirc-count style, IR-verified `__Frame_*`
drive, zero plain calls); guard-let's else-exit path across the split;
the design-101 shape matrix extended with both shapes flipping from
ERROR to EMBED.

## Item 2 — cross-module generic driven templates (design-74 shape 4)
A nested suspending generic call to a template defined in ANOTHER
module, from a driven body. The old `_pristine_` template-capture is
module-local. Extend the capture/instantiation across module
boundaries (the per-instantiation effect re-inference of designs 70/74
is the model — the template AST must be reachable at drive time
regardless of defining module; design 82's per-file std modules make
this shape common). Test: module A defines a generic suspending
free fn + a generic struct with a suspending method; module B drives
both instantiated at two types; both round-trip.

## Item 3 — struct-generic AND method-generic suspending methods (design-74 residue)
`Holder<A> { func m<B>(&self, ...) }` where m suspends — currently a
clean error. Key the frame by BOTH instantiations (design 95's
resolved-signature keying is the mechanism — extend the key with the
method's own type args). Test: two struct insts x two method insts
drive correctly (4 distinct frames).

If any item proves disproportionate, land the others and flag it with
the precise blocker (do not force it) — items are independent.

Bars: full suite (zero xfails) + bootstrap (incl. libs) green per
commit; IR-verify embeds (no silent third outcome — design 101's bar
is the standing bar now). Standing policy; foreground; watchdog;
interruption-safe; skill self-review; docs = skill+spec supported-
shape story updated per item landed, tracker.
