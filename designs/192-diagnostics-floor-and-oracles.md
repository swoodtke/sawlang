# Design 192 — the diagnostics floor, the fuzzer, and the guarded lane

**Status: AUTHORED from design 190's analysis (Aug 9), awaiting user
approval to queue. Payoff (matrix evidence): 9 of the week's findings
wore an ICE face and would surface within HOURS under a corpus fuzzer
(DF-185a — hex enum literals crashing the parser — is the poster child:
a one-token mutation of any existing enum test); both confirmed silent
UAFs (probes exiting 0) become instruction-level crashes under the
guarded lane. Cost (census-priced): the floor is ~50 lines; the fuzzer
is one new tool; the lane is curation of existing machinery.**

## Units

1. **The two typechecker fallthroughs RAISE.** `_check_expression`'s
   `return None` on an unknown node (typechecker/expressions.py:62-65)
   and the statement dispatch's silent skip (statements.py:912-916)
   become loud internal errors naming the node type — mirroring codegen's
   own dispatches (core.py:2604, statements.py:56). Run the suite to
   flush any node type legitimately relying on the skip; each flush is
   its own finding.
2. **The breadcrumb + the missing wrapper.** Codegen's two dispatch
   chokepoints stamp `self._current_node` (every node carries
   line/column — design 126 R1); sawc.py's catch-all prints
   `internal compiler error at FILE:LINE (<NodeType>)` instead of a bare
   message. The TYPECHECKER — currently entirely unwrapped, raw Python
   tracebacks — gets the same wrapper + breadcrumb around check_module /
   finalize_effects. SAW_DEBUG=1 keeps the full traceback. The 94 bare
   codegen raises are NOT individually reworded (the breadcrumb
   obsoletes that); the 3 stray generic raises (NotImplementedError /
   RuntimeError) join the ValueError convention.
3. **The corpus-mutation fuzzer.** `tools/sawfuzz.py`: takes the
   examples/ corpus, applies cheap syntactic mutations (token
   substitution from the language's own vocabulary, literal rewrites —
   decimal→hex/binary/suffixed, operator swaps, delete-a-token,
   duplicate-a-line, swap-two-statements), compiles each mutant, and
   asserts ONE oracle: the compiler either succeeds or exits with a
   clean diagnostic — ANY Python traceback (or post-unit-2
   internal-compiler-error) is a finding, minimized and written to a
   findings directory with its seed. Deterministic per seed (no
   wall-clock/randomness in the mutation choice — seed in, corpus
   order fixed) so a finding replays. Two modes: `--quick N` (N
   mutants, battery-adjacent budget ~1 min) and `--soak` (unbounded,
   run manually/overnight). Wave-bounded subprocess fan-out FROM DAY
   ONE (the DF-182f lesson is a stated requirement).
4. **The guarded concurrency lane.** Per the census: NOT a corpus sweep
   (30-60 min, flaky-adjacent) — a second curated gmgate sub-lane of
   10-15 coroutine/TaskGroup/channel ownership oracles at `-n 5`,
   chosen for frame-handoff, capture, join/teardown, and Data/COW
   shapes (the existing three coro_* entries prove the mechanism).
   Wired into the battery script beside the existing lane. The two
   ex-UAF probe shapes (189's move-root and 188's declared-after,
   now compile errors) get their nearest still-legal cousins in the
   lane so the NEXT hole in that family crashes loudly.
5. **Docs + tracker**: TESTING.md (the fuzzer's modes + the finding
   workflow: a fuzzer finding becomes a DF + pin like any other), the
   battery script gains `--quick` fuzz + the sub-lane, CLAUDE.md's
   battery list updated.

## Gates

Full battery per unit. Unit 1's flush-list is the review surface. Unit
3's acceptance: the fuzzer, seeded over the pre-185 tree, REDISCOVERS
DF-185a (hex enum literal) — the historical-bug replay is the proof the
oracle works. Ten-repeat stability does not apply (no scheduler surface)
except the sub-lane, which is 10× by construction.

## Explicitly out

Grammar-aware generative fuzzing (the mutator is v1; a generator is a
follow-up if the mutator's yield plateaus); differential fuzzing against
a second implementation (none exists yet — parser port material);
runner-integrated ASan-style modes (macOS Guard Malloc is the lane;
Linux sanitizers arrive with CI); rewording the 94 messages.
