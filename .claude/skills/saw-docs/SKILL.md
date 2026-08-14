---
name: saw-docs
description: |
  Writing user-facing Saw documentation — README, LANGUAGE_SPEC prose,
  docstrings, website/tutorial content, release notes. Load BEFORE writing or
  editing any of these. Combines de-LLM'd prose rules with Saw's terminology,
  voice, and code-example conventions so docs read consistent and human. NOT
  for code comments (match surrounding style) or design briefs/tracker
  entries (dense lead-voice is correct there).
---

# Writing Saw documentation

Saw's docs voice: plain, dense, factual, technically precise. A systems
programmer is the reader. Neutral and plain IS the correct human voice for
reference material — never inject marketing, enthusiasm, or filler. Tutorials
may address the reader as "you" and use imperatives ("Run `make test`");
reference material states facts.

## Prose rules (the de-LLM core)

1. **No significance inflation.** Banned framings: "marks a pivotal", "plays a
   crucial/vital role", "underscores/highlights the importance", "testament
   to", "represents a shift", "setting the stage". State the fact; let the
   reader judge weight.
2. **No promotional tone.** Banned: "powerful", "blazing", "seamless",
   "robust", "elegant", "rich", "vibrant", "comprehensive", "groundbreaking",
   "boasts". A capability claim must be checkable — cite the mechanism, a
   test, or a number, or cut the claim.
3. **No fake-depth "-ing" tails.** "…, ensuring memory safety", "…, allowing
   developers to…", "…, showcasing…" — either promote the tail to its own
   sentence with a real mechanism ("The checker rejects X at compile time"),
   or delete it.
4. **AI-vocabulary blacklist** (use plain alternatives): delve, leverage
   (verb), utilize, crucial, pivotal, foster, streamline, seamlessly,
   intricate, landscape/tapestry (abstract), interplay, enhance, additionally
   (sentence-initial — use "also" or restructure), furthermore, moreover,
   "it's worth noting", "importantly", honest/honestly (as praise for one's
   own text or examples — describe what the thing does instead).
5. **Kill filler openers and hedges.** "It should be noted that", "In order
   to" (→ "To"), "As mentioned earlier", "essentially", "simply", "just",
   "easy/easily" (if it were easy the sentence wouldn't be needed).
6. **No rule-of-three padding.** "fast, safe, and reliable" — pick the one
   that matters or give each its own supported sentence.
7. **No negative parallelisms.** "It's not just X — it's Y" is banned.
8. **Em dashes: sparing.** Prefer commas, parentheses, or a new sentence.
   Never more than one em-dash pair per paragraph.
9. **Vary sentence rhythm; tolerate asymmetry.** Uniform medium-length
   sentences and perfectly parallel bullet lists read machine-made. A short
   sentence after a long one is good. Bullets may have unequal depth.
10. **Never invent facts.** No benchmark numbers, version claims, platform
    claims, or history that isn't verifiable in the repo. If a sentence needs
    a fact you don't have, write the version without it.
11. **Headings are nouns, not questions or gerund phrases.** "Ownership", not
    "Understanding Ownership" or "Why Ownership Matters".

## Saw terminology (use these exact terms; never the alternatives)

| Use | Never |
|---|---|
| suspending / sync function | async/await, coroutine-colored |
| task (cooperative unit), thread (OS unit) | goroutine, fiber, green thread |
| driven / spawned (how a frame executes) | scheduled, awaited |
| move, implicit copy, `.copy()`; the three words: `Copy` (the silent tier), `NoCopy`, `ExplicitCopy` | clone, deep copy (unless literally `_deep_copy`); ImplicitCopy (retired) |
| deterministic destruction, `Deinit`, "deinits" | destructor, RAII (except when comparing to C++), finalizer |
| reference `&T` / `&var T` (parameter-only) | borrow checker (Rust's term; Saw: "exclusivity"), pointer (reserve for Unsafe*) |
| Law of Exclusivity | aliasing rules |
| payload (of an Optional/enum case) | wrapped value, inner value |
| short-circuit (`?.`, `??`) | early exit |
| clean error (a rejected program with an anchored diagnostic) | graceful failure |
| freestanding / hosted profile | bare-metal mode, no_std |
| the runtime ABI, seam (`__saw_rt_*`) | intrinsics, syscalls (unless SOS syscalls) |
| trait, conformance, `any Trait` existential | interface, impl, dyn |
| moves/consumes/borrows self (ownership effect of a method) | takes ownership of itself |

Spell compiler/tool names lowercase as they are invoked: `sawc`, `blade`,
`sawlex`. The language is Saw (capital S). Design references ("design 88")
belong in dev docs and briefs, not user-facing pages — user docs cite the
spec section instead.

## Code examples

- Every example COMPILES as shown (or is explicitly marked as a fragment).
  Test the exact text before publishing; drift between docs and compiler is a
  bug (the doc-sync audits exist because of it).
- Minimal but real: prefer the actual std API over pseudo-code; no `foo`/
  `bar` when a domain word is available; no magic numbers (named statics —
  the saw-lang skill's style rule applies inside examples).
- Show failure: examples of fallible APIs handle the `Result` (or
  visibly `try!` with a comment saying why that's acceptable there) — never
  swallow an error to shorten a snippet.
- Show output when it teaches: a `// prints: ...` comment beats prose
  describing the output.
- An example that demonstrates a compile-time REJECTION labels itself
  clearly (`// error: ...` with the real diagnostic text).

## Docstrings (`///`) — see the doc-comment design for mechanics

- First line: one sentence, third-person present, says what the item DOES —
  "Returns the number of live elements." Not "This function will…", not a
  restatement of the signature.
- Then, only if needed: failure modes (what `Err`/`None` MEANS — Saw's
  never-hide-errors culture extends to docs), suspension behavior ("Suspends
  until a peer accepts"), ownership effects ("Consumes the listener",
  "Borrows the buffer for the call"), and panics ("Panics if `i` is out of
  bounds").
- Don't document the obvious (a getter named `len` needs one line, not
  three). Don't repeat types the signature already shows.

## Structure conventions

- README: what it is (two sentences, checkable claims), install/build, one
  working example, where the full docs live. No feature laundry lists.
- Tutorial pages: task-oriented headings, runnable steps, expected output
  after each step.
- Reference pages: signature first, prose second, example last. Consistent
  ordering across every item.
- Error-message docs: quote the REAL diagnostic text (copy from a probe run,
  not from memory).
