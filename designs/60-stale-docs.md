# Design 60 — Stale-spec pass + README refresh (queued Jul 30)

Docs-only brief (plus tiny probes): bring LANGUAGE_SPEC.md, README.md,
and the tracker's stale-doc ledger in line with the compiler as it
ACTUALLY is after designs 44–59. No language changes; no new tests
except probe scratch files. Discipline: NEVER mark something as
implemented without a compiling probe (.build/scratch/), and never
delete a "planned" marker without either probing it or citing the
landed design that shipped it.

## Part 1 — the tracker's named stale-spec items
(from "Resolved-by-decision / stale-spec"; each = find every spec
mention, fix, done)
- Rc: Arc-only was decided (design 16) — remove/replace Rc<T>
  mentions (CLAUDE.md "Rc/Arc (planned)" line included).
- Thread API + async/await: colorless decided — purge aspirational
  async/await/thread-API text; point at the coroutine/TaskGroup
  sections (designs 44/45/52/52b are landed reality).
- `=>` arrows: superseded — sweep any remaining arrow examples.
- swapAt: landed as Vector.swap (brief 40) — fix stale mentions.
- StringBuilder "future work" note: landed (38) — remove.
- `dyn` reservation: retired by D16 (`any` shipped, design 51) —
  fix the reserved-words appendix if it still lists `dyn`.

## Part 2 — the four VERIFY-then-fix contradictions
Probe each with a scratch compile, then make spec and tracker agree
with reality:
1. Multiple trait bounds `T: A + B` — probably landed.
2. Glob imports (`import mod.*` or spec's spelling) — probably landed.
3. Scoped visibility (`public(package)` etc.) — probably landed
   (visibility_package tests exist).
4. Named tuple field access + `.value` on distinct types — probably
   NOT landed (aspirational examples): mark clearly as planned or
   remove the examples.

## Part 3 — general staleness sweep of LANGUAGE_SPEC.md
Grep for "planned", "future", "not yet", "will be", "TODO", "coming"
markers; for each, probe or cite: either the feature landed (fix the
marker, correct the example to compiling syntax) or it didn't (keep
the marker, ensure the example is clearly labeled aspirational).
Known recent landings to reconcile (probe only where in doubt —
designs cite the reality): overloading (55), Printable/Error/default
bodies/erased Results (56), HashMap→Map + Set + collection/Vector
literals (54), visitors/snapshots + to_int/to_float + DF3 + std.time
+ Int/Float extensions (57), attributes/@export/@section/Never (58),
default params/`..=`/enumerated/limits/suffixes/`\u{}`/import-as/
static_assert/`let _` (53), `any Trait` (51), statics/Atomic (41),
allocators/Box/slab (37/42), UnsafeMemory (46), platform Int (47),
bitwise (50), panic/assert + blade test (49), Equatable (32) /
Comparable/Hashable (48). The spec sections those briefs edited are
presumed current — the sweep is for OLDER text contradicting them.
- Also verify the spec's example code blocks in touched sections
  actually compile (spot-probe the ones you edit; fix syntax drift).

## Part 4 — README.md full refresh
The README predates most of the language. Rewrite against CLAUDE.md's
current-features (source of truth) + the spec:
- Fix wrong facts: clone URL is fictional (drop the git-clone step;
  describe the repo layout instead or use a placeholder note); install/
  run instructions must match CLAUDE.md (.venv, ./.venv/bin/python
  sawc/sawc.py, -o semantics, -O0/default pipeline flags list);
  "Map<K, V> - Hash maps" is now true but Vector/Map/Set/String std
  list needs the real API names; Python 3.8+ → what .venv actually is
  (3.14); test section: make test needs the venv activated.
- Feature sections: add the headline features landed since the
  README was written — pick the ones that sell the language, not an
  exhaustive changelog: Copy trait family (already there, keep),
  overloading, Printable + interpolation of user types, Error +
  erased Results, traits with default bodies, `any Trait`
  existentials, colorless concurrency (TaskGroup/spawn/join/cancel,
  yield/sleep — brief example), allocator type parameter + Box/slab
  (the kernel story), UnsafeMemory/@export/@section/static_assert
  (the embedded story teaser), collection literals + Set, default
  params, `..=`, literal suffixes, `let _`, panic/assert, blade test.
  Keep the quick-example style: short compiling snippets (probe each
  snippet you add).
- Status section: replace the long bullet lists with a shorter
  "supports" summary + pointer to CLAUDE.md/spec (the lists rot —
  say so implicitly by linking).
- Keep tone/structure of the existing README (it's good marketing
  copy); this is a refresh, not a rewrite from scratch.
- Blade section: mention `blade test` and the current milestone
  reality (built in Saw, real TOML/manifest/builder).
- Do NOT invent performance claims or a license/community that
  doesn't exist (check LICENSE file exists before linking it).

## Part 5 — CLAUDE.md drift check (light)
CLAUDE.md was updated per-brief and is mostly current; just verify
the "Current Features" opening list and "planned" parentheticals
(e.g. Rc, Mutex/RwLock lines) against reality and fix stragglers.

## Items (suggested commit units)
1. Part 1 + Part 2 (tracker named items + the four probes) — spec +
   tracker edits, probe results in the commit message or tracker.
   [WORKTREE AMENDMENT: tracker edits go in your final report, not
   in designs/todo.md]
2. Part 3 sweep — spec.
3. Part 4 README refresh (+ snippet probes).
4. Part 5 + close-out. [WORKTREE AMENDMENT: tracker close-out text
   goes in your final report]

## Hazards
- Spec examples must COMPILE as written where they're presented as
  current syntax — probe, don't eyeball; syntax drifted (e.g. `..=`,
  suffixes, literals, `@export`) and half-updated examples are worse
  than stale ones.
- Don't touch normative sections landed by recent briefs except where
  they contradict each other; when two sections disagree, the LATER
  design's text wins (cite it).
- README snippets are the project's front door — every one must be a
  real compiling program (or clearly elided with `...`).
Full suite once at the end (docs shouldn't break it, but the probe
files must not leak into examples/); zero xfails.
