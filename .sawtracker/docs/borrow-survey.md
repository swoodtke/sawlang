# Borrow survey: the trees measured against SL:borrowing

This is the read-only survey approved in SL:borrowing §11. It lists the place
uses and closure-borrow calls OBSERVED by today's pre-coroutine place-lowering
funnel in the trees below, sorts each by the form it takes under the ruled
design, and flags the shapes the rules make awkward or refuse. The measurements
were taken on 2026-09-24 against sawlang `main` (338914a5) and sawos 7bc6d3c,
and classified against SL:borrowing as of r4–r5. Later rulings (r7–r9:
`default:` is lazy, static roots are the `unsafe` author's obligation) postdate
the classification. No tracked file was changed.

**Coverage, and what a zero means.** The instrument is the compiler's own
place-lowering pass. Each site was recorded at
`place_uses._PlaceUses._window_call` after a full typecheck of a real entry
point. That funnel does not see trait default bodies, static initializers,
default parameter values, entries that fail to typecheck, or synthesized and
monomorphized declarations, and the root-capture check (E-345) matches names,
so it misses aliases (see §Limitations). A zero below means **none observed
within this coverage**, not evidence that the form does not exist. Bypassed
funnels are exactly where earlier bugs hid. None of the counts below comes from grep. A grep was used once, as
a cross-check on the sawos total, and it agreed exactly (see §Methodology).

**Headline numbers:**
- Outside the kernel the retirements are small. std, blade, libs and devtools
  hold 280 place uses between them. 80 of those change spelling (A1, B, Fwd,
  G3, G4). The rest keep their spelling: plain getitem reads and `get()` reads
  of Copy elements.
- sawos is the volume. It has 644 place uses, and 200 of them need
  `borrow var`. The other 444 keep their spelling: 34 whole-slot stores
  (setitem) and 410 field reads. Those 410 stay plain getitem only if `Slab.[]`
  gets a `&self` variant, which `@synthesize(shared)` should give it (§F).
- The examples corpus has 907 place uses in files that are not error tests.
  It is also where every Map-subscript, `?.`-write and presence-test shape
  lives. The trees contain none of those.
- No closure-borrow call observed in the typechecked trees captures its own
  root by name (the SL-345 shape; aliases are not detected). No borrow
  observed in the typechecked trees is held across a suspension.

## Summary table

Place uses are counted once per source site. The outer hop of a nested chain
(`b[0][1]`) is not counted again. The only one in the typechecked trees is at
`libs/toml`.

| Row | Becomes | std | blade | libs | devtools | sawos | Exactness |
|---|---|---|---|---|---|---|---|
| **A0** whole-element store `v[i] = x` | setitem, same spelling | 2 | 0 | 0 | 0 | 34 | type-exact |
| **A1** field write `v[i].f = x` / `op=` | `borrow var` statement form | 12 | 0 | 0 | 13 | 196 | type-exact |
| **A2** whole-element compound `v[i] op= x` | getitem+setitem (Copy) | 0 | 0 | 0 | 0 | 0 | type-exact |
| **A3** mutating call through a place `v[i].m()` | `borrow var` statement form | 0 | 0 | 0 | 0 | 4 | type-exact |
| **A4** forced-lend store `m[k]! = v` | `m[k] = v` (semantics change, K7) | 0 | 0 | 0 | 0 | 0 | type-exact |
| **B** `&v[i]` / `&var v[i]` argument | block form (no statement spelling, K6) | 0 | 2 | 0 | 0 | 0 | type-exact |
| **C** `m[k]?.f = v` | `m.find(k)` block | 0 | 0 | 0 | 0 | 0 | type-exact |
| **D1** Map `m[k]` read as an optional | `m.get(k)` | 0 | 0 | 0 | 0 | 0 | type-exact |
| **D2** `.get(i)` read as an optional, Copy element | same spelling, now a copy | 8 | 46 | 3 | 15 | 0 | type-exact |
| **D3** presence test `if let _ = m[k]` | `get`/`contains_key`/`find` (K8) | 0 | 0 | 0 | 0 | 0 | type-exact |
| **D4** get-or-insert | `default:` (§5.4) | 0 | 0 | 0 | 0 | 0 | heuristic |
| **E** std closure-borrow API call | `borrow` over the new accessor | 28 | 1 | 0 | 0 (+6 †) | 0 | type-exact († parser-only) |
| **E-345** …whose closure names the call's own root | — | 0 | 0 | 0 | 0 | 0 | AST name match |
| **F** `borrows` declarations | §3 row; `@synthesize(shared)` | 14 | 0 | 3 | 0 | 1 | type-exact + probe |
| **Fwd** `lend` forwarded through another accessor | not addressed by the doc (K2) | 4 ‡ | 0 | 3 | 0 | 0 | type-exact |
| **G1** value read of a Copy place `let x = v[i]` | getitem, same spelling | 40 | 2 | 0 | 22 | 0 | type-exact |
| **G2** read through a Copy element `v[i].f` | getitem then `.f`, same spelling (K13) | 22 | 7 | 5 | 28 | 410 | type-exact |
| **G3** read through a non-Copy/abstract element | `borrow let` statement form | 4 | 18 | 21 | 0 | 0 | type-exact |
| **G4** `match` on a place (abstract element) | `borrow let` block | 7 ‡ | 0 | 0 | 0 | 0 | type-exact |
| **H** two uses of one root in one statement | see §H; 0 conflicts | 1 | 0 | 0 | 6 | 72 | type-exact grouping, rule applied by hand |
| **I** slice candidates (triples + range APIs) | `&[T]` / `s[a..b]` | 8 + 6 | 1 + 9 | 0 + 11 | 0 + 23 | 0 | heuristic (triples); type-exact (calls) |
| **J** borrow held across a suspension | §2.5 | 0 | 0 | 0 | 0 | 0 | type-assisted + probes |
| total place uses (A through G) | | 95 | 75 | 32 | 78 | 644 | |

‡ The four `match self.slots[i] { … lend v }` sites inside Map's accessors
(`map.saw:265, 285, 417, 425`) are forwarded lends. They are counted under G4
and listed under Fwd.
† `devtools/dogfood/programs/w1_limiter.saw` is one of five dogfood programs
that no longer typecheck on main (design-234 fallible constructors; see
Methodology). Its six `Arc<Mutex<…>>.lock({…})` calls were counted from the
parser AST alone.

### The examples corpus (counts only)

The 2,681 entry files include `EXPECT: error` tests. 1,699 non-error files
reached place lowering. Most error tests stop earlier, but 76 reached lowering
and are counted in their own column. Columns are counts of sites.

| Row | non-error | error tests | of which conformance/ |
|---|---|---|---|
| A0 setitem | 38 | 5 | 6 |
| A1 field write | 38 | 8 | 5 |
| A2 compound whole (getitem+setitem) | 29 | 7 | 18 |
| A3 mutating call through a place | 23 | 5 | 3 |
| A4 forced-lend store `m[k]! = v` | 4 | 1 | 1 |
| B `&`/`&var` place argument | 27 | 3 | 7 |
| C `x[k]?.f = v` | 10 | 1 | 1 |
| D1 Map `m[k]` read as an optional | 25 | 1 | 0 |
| D2 `.get()` read as an optional | 121 | 0 | 5 |
| D3 presence test `if let _ = <conditional place>` | 31 | 0 | 8 |
| D5 another named conditional lend, read as an optional | 8 | 0 | 0 |
| Fwd lend forwarding | 16 | 3 | 6 |
| G1 value read, Copy | 288 | 15 | 63 |
| G2 read through a Copy element | 114 | 7 | 11 |
| G3 read through a non-Copy element | 82 | 1 | 6 |
| G4 match / borrowing operand / presence desugar | 53 | 4 | 7 |
| **total** | **907** (214 files) | **61** (19 files) | **147** (35 files) |

The accessors behind those sites: Vector.[] 283, Vector.get 124, Map.get 78,
Map.[] 76, Data.[] 39, and 30-odd user accessors. The rest of the examples
corpus, counted from the non-error files:
- 172 std closure-borrow calls: `Arc<Mutex>.lock` 32, Vector.each 27,
  Mutex.lock 22, Vector.fold 18, SpinLock.lock 14, Vector.with_ref 11,
  Map.each 10, Arc.with_unique 9, Vector.map 9, Vector.with_var_ref 5,
  Map.each_value 4, Map.each_key 3, Set.each 2, Vector.sort_by 2,
  SpinLock.try_lock 2, Vector.each_indexed 2.
- 16 user-defined closure APIs that lend references.
- 20 closures that only capture references (`[&var x]`).
- 113 `borrows` declarations, 15 of which write `self` (so `@synthesize(shared)`
  would be refused for them).
- 267 `for` loops over a borrowing iterator. In 88 of them, spread over
  12 files, the loop body contains a suspending call (J).
- 14 DF-218j hoists.
- 2 closures that name the call's own root (K10).

---

## A. Inline place writes

These are 12 in std, 13 in devtools and 200 in sawos (196 field writes and 4
mutating calls). Every one lowers today through `_assignment`, or through
`_chain_window` with an exclusive window, and becomes `borrow var` statement
form. Every element involved is Copy-tier (tier `free`), so the §2.2
early-close rule applies wherever the right-hand side reads the same root
(§H). Whole-element stores (A0) are setitem and keep their spelling. No tree
has a whole-element compound (A2) or a forced-lend store (A4).

- `sawc/std/cbor.saw:283` `self.levels[last].key_start = start` (Vector<CborLevel>)
- `devtools/bench/warehouse/warehouse.saw:89` `self.robots[i].battery -= 1`
- `sawos/kernel/core/process.saw:1217` `PROCESSES[p].refs = PROCESSES[p].refs + 1`
- `sawos/kernel/core/irq.saw:56` `TIMERS[slot].fire(now)` (A3; `fire` is `&var self`, time.saw:273)
- A0: `sawc/std/cbor.saw:509` `stack[last] = rem - 1`; `sawos/kernel/core/refs.saw:611` `EVENTS[slot] = EventSlot(...)`

## B. `&var x[i]` / `&x[i]` arguments

There are only two, both in blade, and both hand a non-Copy
`TomlDoc.section_at` lend to a helper:
- `blade/src/sosimg.saw:241` `try priorities_from(&doc.section_at(index))`
- `blade/src/sosimg.saw:270` `toolchain_fields_from(&doc.section_at(index))`

Block form works for both. §2.2 gives no statement-form spelling for a place
handed over as a reference argument (K6).

## C. `m[k]?.f = v`

There are none in the trees. The examples have 10, for example:
- `examples/optional_generic_chain_assign_place_head.saw:31` `m["x"]?.value = 42`
- `examples/optional_chain_compound_assign.saw:65` `scores["a"]?.x += 20`
- `examples/optional_generic_chain_assign_place_head.saw:36`
  `guard let _ = m["nope"]?.value = 7 else {…}`. This consumes "did it write",
  and a `find` block has to spell that out (K9).

## D. Map optional reads; get-or-insert

- **No tree uses a Map subscript at all** (D1 = 0, D3 = 0). All six Map
  place uses in the trees are `m.get(k)` on String/ManifestEntry values, all
  Copy-tier, and they keep their spelling:
  - `blade/src/cli.saw:101` `let target = scanned.flags.get("--target") ?? ""`
  - `blade/src/cli.saw:133` `if let path_loc = scanned.flags.get("--path") {`
  - `devtools/irdet/src/main.saw:800` `entry = manifest!.get(rel)`
- D2 is mostly `Vector.get(i)` read as an optional on Copy elements:
  - `blade/src/resolver.saw:99` `self.names.get(i) ?? ""`
  - `sawc/std/process.saw:238` `if let existing = self.envs.get(i) {`
- **Get-or-insert (D4):** the heuristic found 0 in the trees and 0 in the
  examples. It looks for an `insert`/`set` on the same root in the enclosing
  `if`/`if let`/`guard`, or in the statement holding a `??`. Blind spot: a
  get-or-insert split across unrelated statements is not detected.
- The examples have 25 D1 sites, for example
  `examples/coro_nested_iflet_struct_init.saw:57` `m["sum"] ?? -1`. They have
  31 D3 presence tests, of which 7 are on a Map (3 of those with non-Copy
  values), for example `examples/map_subscript_place.saw:57` `if let _ = m["zz"] {`.
- **Writes through `get` today:** `get` is a conditional PLACE today, and a
  write through it lands in the container. §5.1 makes `get` the optional
  VALUE. The trees have no write or non-Copy chain through std `get`. In the
  non-error examples, 31 std `Vector.get`/`Map.get` uses cannot be served by a
  value `get` (K14):
  - 16 non-Copy chains
  - 11 presence tests, 6 of them on non-Copy values
  - 2 `?.` writes
  - 1 compound write
  - 1 borrowing operand on a non-Copy value

## E. Closure-borrow API calls

std exposes 15 closure-borrow APIs, enumerated from its declarations: every
function-typed parameter whose own parameters include a reference.

| API | lends |
|---|---|
| Vector.with_ref / with_var_ref | `&T` / `&var T`, closure `sync` |
| Arc.with_unique | `&var T`, closure `sync`, returns `R?` |
| Mutex.lock / SpinLock.lock / SpinLock.try_lock | `&var T`, closure `sync`, `(&self)` |
| Vector.each / each_indexed / map / fold / sort_by | `&T` (sort_by: two at once), closure not sync |
| Map.each / each_key / each_value, Set.each | `&K`/`&V`/`&T`, closure not sync |

Call sites in the trees:
- **std (28):**
  - Vector.with_var_ref 16 (`taskgroup.saw` 1142…2489) and Vector.with_ref 2
    (`taskgroup.saw:1140, 1146`).
  - Arc.with_unique 3 (`data.saw:463, 499, 512`).
  - Vector.each 4 (`map.saw:333, 345, 357`, `json.saw:1316`).
  - Map.each 1 (`json.saw:1333`), each_key 1 (`map.saw:379`), each_value 1
    (`map.saw:392`).
- **blade (1):** `blade/tests/df3_map_time.saw:21` `m.each_value { [&var sum] v in … }`.
- **libs, devtools (typechecked), sawos:** none. The stale
  `w1_limiter.saw:55, 61, 70, 75, 102, 103` has six `Arc<Mutex>.lock({…})`
  calls, counted by parser only.

The call's result is used as a value (`let x = …`, `return …`) in 12 of the
16 with_var_ref calls, both with_ref calls and 1 of the 3 with_unique calls.

**SL-345 shape:** none of the 29 tree closures names its call's own root (the
check matches the closure's capture list plus every identifier in its body
against the receiver's root). The examples have two (see K10):
- `examples/spinlock_basic.saw:62` re-enters `STATS` through `try_lock`
  inside `STATS.lock`.
- `examples/closure_captures_self.saw:37`
  `self.lend_n({ v in self.n + v })` is a user API with a shared read, which
  §9 keeps legal.

## F. Existing `borrows` declarations (18)

| Accessor | Declaration | §3 row | `@synthesize(shared)` |
|---|---|---|---|
| Vector.[] `vector.saw:88` | `(&var self, index) unsafe borrows -> &var T` | 3 | expected to succeed: lends only |
| Vector.get `vector.saw:110` | `(&var self, index) unsafe borrows -> &var T?` | 3 (conditional) | expected to succeed |
| Map.[] `map.saw:258`, Map.get `map.saw:280` | `(&var self, key) borrows -> &var V?` | 3 (conditional) | expected to succeed; forwards through Vector.[] (needs Vector's shared variant first) |
| Map._key_ref / _value_ref `map.saw:416, 424` | `(&self, idx) borrows -> &K? / &V?` | 1 | already shared |
| Data.[] `data.saw:185` | `(&var self, index) unsafe borrows -> &var UInt8` | 3 | **refused as written**: copy-on-write `_make_ready` under `#lend_var` (K1) |
| Box.value `box.saw:50` | `(&var self) unsafe borrows -> &var T` | 3 | expected to succeed |
| Slot.value `compiler/frame.saw:106` | `(&var self) borrows -> &var T` | 3 | expected to succeed |
| UnsafeRef.deref `compiler/frame.saw:151` | `(&var self) unsafe borrows -> &var T` | 3 | expected to succeed |
| JsonValue.as_array / as_object `json.saw:1413, 1426` | `(&var self) borrows -> &var …?` | 3 (conditional) | expected to succeed |
| Vector.iter / enumerated `vector.saw:487, 494` | `(&self) borrows -> VectorIterator<T, A>` (borrowing struct) | **no row** (K3) | n/a |
| toml table / section_at / section `lib.saw:160, 354, 370` | `(&self, …) borrows -> &T[?]` | 1 | already shared |
| sawos Slab.[] `kernel/core/slab.saw:209` | `(&var self, i) unsafe borrows -> &var T` | 3 | expected to succeed: bounds check, then lend `self.inline[i]` or `p[0]` |

The evidence behind the synthesis column:
1. The compiler already typechecks each `-> &var T` accessor's shared
   specialization and records any receiver mutation it sees
   (`Method.place_receiver_mutation`, SL-333 R4). That field is `None` for
   all 18.
2. `probe_f_shared_ok.saw` declares each lend-only body shape under `(&self)
   borrows -> &T`, and it compiles and runs, printing `3` / `7` / `3`. The
   shapes are Slab's inline-array lend, Slot's guard-then-lend, JsonValue's
   `match self` payload lend and Vector's lend through a held pointer.
3. The Data.[] shape without its `#lend_var` gate is refused. See K1.

Every place accessor in the trees except iter/enumerated is `sync`
(`is_sync` on all 16).

## G. Value reads of a place

- **G1/G2 (Copy):** these keep their spelling as getitem. There are 40/22 in
  std, 2/7 in blade, 0/5 in libs, 22/28 in devtools and 0/410 in sawos. The
  getitem derivation needs a `&self` place accessor (§5.2), so the sawos 410
  and the std Vector sites depend on `@synthesize(shared)` for Slab.[] and
  Vector.[].
- **Non-Copy (G3/G4) — they need `borrow let` or `.copy()`:**
  - blade has 18, all `doc.section_at(x).<m>(…)` on `TomlSection` (NoCopy),
    for example `blade/src/manifest.saw:160` `let name = doc.section_at(pkg).get("name") ?? "unknown"`.
  - libs has 21. Five are in `libs/toml/src/lib.saw`: `:141`
    `if self.tables[i].key.equals(key) {`, `:171`
    `return self.tables[i].get(subkey)`, `:187`
    `try! out.push(self.tables[j].key)`, `:313` and `:324`. The other 16 are
    in `libs/toml/tests/*` (`doc.section_at(deps).is_table(...)` inside
    `assert(...)`).
  - std has 4 G3: `map.saw:444, 445, 466, 467` `self._key_ref(i)!.copy()`
    (abstract `K`/`V`).
  - std has 7 G4: `match self.slots[idx]` over the abstract `MapSlot<K, V>`
    at `map.saw:63, 75, 164, 265, 285, 417, 425`.
  - devtools and sawos have none.

## H. Two uses of one root in one statement

Sites were grouped by enclosing statement (the instrument's statement stack),
then by root. There are 79 groups:

| Tree | Shape | Count | Under the ruled rules |
|---|---|---|---|
| sawos | 1: read-modify-write of one slot | 41 | OK: RHS is a Copy read, evaluated first, closed before the `borrow var` opens (§2.2 early-close) |
| sawos | 2: two reads of one slot in one call/expression | 26 | OK: two getitem copies. Needs Slab.[]'s `&self` variant; without it each `borrow let` charges the static root exclusively and they conflict |
| sawos | 3: copy between two slots | 4 | OK: same as shape 1 |
| sawos | write + reads of mixed slots | 1 | OK: `objects.saw:1159` `FREE_RANGES[into].len = FREE_RANGES[into].len + FREE_RANGES[next].len` |
| devtools | two reads, one slot / distinct slots | 3 + 3 | OK: getitem (`warehouse.saw:81, 91, 189`, `llm_client.saw:375, 385`) |
| std | reads of distinct slots | 1 | OK: `taskgroup.saw:1343` |

- **No group in any typechecked tree still conflicts** under the early-close
  rule plus `@synthesize(shared)`. The conflicting shapes are two references
  into one root in one call, or a place beside a `&var` of its root. Design
  188 already refuses those today, so no code that compiles contains them.
- **Swaps / `pair` / `split_at` candidates:** 0. No A0 pair in the trees
  swaps two slots of one root, and no call takes two references into one root.
- All 46 sawos write groups (shapes 1 and 3, plus the mixed one) are exactly
  the sites the compiler hoists today (DF-218j `_rhs_names_root`: 46 hoists
  recorded, all in sawos).
- The three shapes from t8, answered:
  - `process.saw:1217` (shape 1) becomes `borrow var PROCESSES[p].refs += 1`
    or `… = PROCESSES[p].refs + 1`.
  - `waitables.saw:749` `waitable_ready(ATTACHMENTS[a].kind, ATTACHMENTS[a].target)`
    (shape 2) needs no borrow: getitem copies.
  - `threads.saw:423` `THREADS[slot].link = THREADS[target].joiners`
    (shape 3) becomes `borrow var THREADS[slot].link = THREADS[target].joiners`.
- **t8's open question, "are the kernel slab element structs Copy-tier?": yes,
  all 13.** Each one's copy tier is `free`, the trivially copyable tier:
  Attachment, EventSlot, Exchange, FreeRange, InterruptSlot, IoMemorySlot,
  MappingSlot, MemorySlot, PipeSlot, ProcessSlot, ThreadSlot, TimerSlot and
  WaiterSlot (`Namespace.copy_tier` at each site).

## I. Slice candidates

- **(buffer, offset, length) signatures.** These were filtered by parameter
  types, then read by hand. The heuristic's 25 raw hits included allocator
  `(ptr, size, align)`, decoder limit parameters and `Vector.swap(i, j)`, and
  those were dropped.
  - `sawc/std/net.saw:234, 240` `tcp_try_read/tcp_try_write(fd, buf: UnsafePointer<Int8>, len)`:
    the extern-shaped pointer+length.
  - `sawc/std/net.saw:378, 384` `net_write_str_once(fd, s, off)`, `net_write_data_once(fd, bytes: &Data, off)`:
    a buffer plus an offset, the `&buf[off..]` shape.
  - `sawc/std/data.saw:90` `DataBuf.absorb(index, src: UnsafePointer<Int8>, len)`.
  - `sawc/std/string.saw:176, 371, 622` `_substring(start, length)`, `substring(start, end)`, `_decode_at(i, len)`.
  - `sawc/std/data.saw:344` `Data.slice(start, end) -> Data?`.
  - `blade/tests/sosimg_wire.saw:192` `check_image(img: &Data, entry, content_off)`.
- **Range-API calls (type-exact):**

  | API | std | blade | libs | devtools |
  |---|---|---|---|---|
  | `String.substring` | 5 | 8 | 11 | 10 |
  | `Data.slice` | 1 | 1 | 0 | 13 |

  Examples: `libs/toml/src/lib.saw:276` `trimmed.substring(0, eq_pos)`,
  `devtools/dogfood/programs/llm_client.saw:415` `buf.slice(0, end)` (followed
  by `guard let hb = head_bytes else {…}`), and `sawc/std/cbor.saw:681`
  `guard let raw = self.input.slice(self.pos, self.pos + n) else {…}`.
  `Data.slice` returns `Data?` (None out of range), while §6 has `s[a..b]`
  panic. Each call site's absent-range handling therefore changes when it is
  migrated. That was not audited site by site.
- **Manual sub-range loops:** 0 real ones. The heuristic looks for a
  `for i in a..b` whose bounds are not `0..x.len()` and whose body indexes by
  `i`. Its 2 hits (`warehouse.saw:99, 188`) are whole-array loops over a
  constant bound. Blind spot: `while` loops with hand-maintained indices are
  not scanned.
- sawos kernel: none. Kernel buffers are carried as `UInt` addresses, not
  typed buffers.

## J. Borrows held across a suspension

- **Trees: 0.**
  - 15 `for` loops over a borrowing iterator (`v.iter()`) exist in the trees.
    Exactly one sits in a frame-boundary function (`blade/src/tester.saw:200`),
    and its body is `print` only (read by hand).
  - The typechecked trees have no closure-borrow body or place window that
    suspends. The compiler refuses both today (the probes below).
- **Examples: 88 `for`-over-iterator loops in 12 files have a suspending call
  in the body.** They are the K133–K140 conformance family ("window spans a
  suspension"), plus `borrowing_field_reads_compose.saw:100` and
  `borrowing_rules_resolve_aliases.saw:115`. The count comes from the effect
  graph's frame-boundary answer on each call in the loop body. The detector
  was validated on `probe_j_iter.saw` (it finds `yield_now`).
- Today's behavior, from compiles:
  - `probe_j_iter.saw` (suspension inside `for x in v.iter()` in a spawned
    task) compiles and prints `6`.
  - `probe_j_withref.saw`: ``error: cannot suspend in a `sync` closure context: closure calls yield_now (closure suspends at line 7)``
  - `probe_j_each.saw`: ``error: coroutine transform: the suspending call `yield_now(...)` appears inside a CLOSURE BODY in driven `work`, and a closure body is not driven``
  - `probe_j_window.saw`, `w[0].bump()` with a suspending `&var self` method:
    ``error: cannot suspend in a `sync` closure context: closure calls `Counter.bump` → yield_now``.
    The same error comes from `bump_ref(&var w[1])` for `bump_ref`.

  So §2.5 ("a borrow may stay open across a suspension unless its accessor is
  `sync`") widens today's language. Today the only borrow that spans a
  suspension is the borrowing-struct `for` window, which §3 does not cover
  (K3).

---

## K. What the rules make awkward or refuse

Each item gives the sites, then one line on why.

1. **Whether `@synthesize(shared)` understands Data.[]'s `#lend_var` gate is unspecified.**
   - `sawc/std/data.saw:185-196`. The checked-in accessor gates its CoW
     separation (`self._make_ready(...)`) with `#lend_var`, and §4 synthesizes
     by typechecking "the same body again" under `&self`. The doc does not
     mention `#lend_var`.
   - What the probe shows: with the gate REMOVED, that body under a shared
     signature is refused (``cannot call `&var self` method `make_ready` on a
     `&self` receiver``, `probe_f_shared.saw:42`). It does not show that the
     gated current body is refused. The open contract is whether
     specialization understands `#lend_var`.
   - It need not block Data getitem (std `cbor.saw:239-240`, 39 example
     sites): the design already admits an explicitly written shared accessor
     that bounds-checks and lends without CoW separation, paired with the
     exclusive accessor that separates. Writable-lend separation stays the
     invariant. (Thread t4.)
2. **Lend forwarding is not addressed.**
   - Sites: `libs/toml/src/lib.saw:162, 358, 372` (`lend self.sections[i]`);
     `sawc/std/map.saw:265, 285, 417, 425`
     (`match self.slots[b] { case Occupied(_, v) -> { lend v } }`); 16
     non-error examples.
   - §1 says a `borrows` function is called only through `borrow`. A `lend`
     whose operand is another accessor's place is such a call, and the doc
     says nothing about it.
3. **Borrowing-struct accessors have no §3 row.** K3 and K4 are semantic
   migration prerequisites, not just awkward spellings (thread t3). They
   should be decided together with K2 (forwarding) and K5 (value-yielding
   borrow blocks), using today's generic and NoCopy cases as acceptance
   examples.
   - The accessors are `Vector.iter` / `Vector.enumerated`
     (`(&self) borrows -> VectorIterator<T, A>`, `vector.saw:487, 494`).
   - Their `for`-head window has 15 sites in the trees, 267 in the examples,
     and 88 examples suspend inside it.
   - It is the one borrow today that spans a suspension (§2.5). The design
     does not name it.
4. **Visitor APIs have no `borrows`-accessor shape.**
   - The APIs: Vector.each / each_indexed / map / fold / sort_by, Map.each /
     each_key / each_value, Set.each.
   - Sites: std 7, blade 1, examples 77.
   - Why: they lend many places one after another. `lend` inside a loop is
     refused today, and the skill says a body that has to search splits in
     two. `sort_by` lends two elements of one root at once, which is §7's
     `pair` shape with no index guard.
   - `map.saw:320-322` records why they are closures: "a window's body is
     `sync`, which would force `sync` onto every visitor's closure type".
   - Replacing a visitor with `for` over `iter()` is NOT equivalent today:
     `iter`/`enumerated` yield owned elements under `T: Copy`
     (`vector.saw:478-495`), while `each`/`each_indexed` lend `&T` with no
     Copy bound (`vector.saw:464-467`), so NoCopy element types would lose
     traversal. `sort_by` also needs a caller-supplied comparator, which no
     single-place accessor provides. So the design must either specify
     borrowed-element traversal or explicitly retain these higher-order APIs.
     Moving the one-shot guard APIs (`with_ref`, `with_var_ref`, `lock`,
     `with_unique`) to `borrows` does not by itself replace the visitors.
5. **Some closure bodies whose value is used touch the place more than once.**
   - `taskgroup.saw:1554` and `:2106` call
     `__park_io_runnable(f!.wake_reason(), f!.is_cancelled(), f!.io_deadline(), now)`.
     Under the early-close rule each of those becomes a separate borrow.
   - `taskgroup.saw:2445` needs the binding across a `match` with arms:
     `match f!.resume() { case Pending -> __ResumeOutcome(done: false, wake: f!.wake_reason()), … }`.
     That needs a block form that yields a value, and whether `borrow … { }`
     is an expression is unstated.
   - 15 of the 21 std with_ref/with_var_ref/with_unique calls use the
     closure's result.
6. **A place handed over as a reference argument has no statement spelling.**
   - Sites: blade `sosimg.saw:241, 270`; 27 non-error examples.
   - §2.2's prefix rule is shown for writes, method calls and reads, and §9
     retires `bump(&var g[4])`. The inline replacement (`bump(&var borrow var g[4])`?)
     is not given, so only the block form applies. Thread t13 (`checksum(&buf[4..])`)
     is the slice version of the same question.
7. **The literal migration of `m[k]! = v` changes behavior.**
   - Sites: 4 non-error examples (e.g. `examples/place_assignment_targets.saw:44`,
     `examples/place_two_windows_one_nocopy_root.saw:80` `m["a"]! = m["b"]! + 10`);
     0 in the trees.
   - Today the `!` panics on an absent key (`probe_k_forced.saw` prints
     `panic at probe_k_forced.saw:13: Map.[]: no place to lend`, exit 134).
     §5.1's setitem `m[k] = v` inserts instead.
8. **Presence tests have no one-line form for non-Copy values.**
   - Sites: 31 non-error examples test the presence of a conditional place
     (`if let _ = <place>`), and 17 of those are on non-Copy elements. 7 are
     on a Map (3 non-Copy), e.g. `examples/map_subscript_place.saw:57`
     `if let _ = m["zz"] {`.
   - The new `[]` panics, and a value `get` cannot copy a non-Copy element,
     so such a test becomes `contains_key` (Map only) or a `find` block.
9. **Chain writes through a conditional lend become a block.**
   - Sites: 10 non-error examples. The worst is
     `examples/optional_generic_chain_assign_place_head.saw:36`
     `guard let _ = m["nope"]?.value = 7 else {…}`.
   - Under §2.4 the "did it write" `Bool` has to be rebuilt from an
     `if let` inside a `find` block.
10. **Re-entry through the same name in a lock body becomes a compile error.**
    - Site: `examples/spinlock_basic.saw:62-63`,
      `STATS.lock({ _c in if let _v = STATS.try_lock({ inner in inner.hits }) {…} })`.
    - This example pins "`try_lock` inside a critical section refuses rather
      than deadlocking". §8 makes it a compile error, so the pin changes kind.
11. **Every sawos borrow is rooted in an `unsafe static var`.**
    - Scope: all 644 sites, over 13 `Slab` statics.
    - SETTLED since the survey ran (SL:borrowing r7, §8a): a borrow rooted in
      an `unsafe static var` is the `unsafe` author's obligation, with an
      optional `-W` warning. The fact it rests on remains: the block form
      holds `&var` into a static across any call in the block, and a
      per-function exclusivity check cannot see a static reached from a
      callee. The kernel authors carry that obligation for all 644 sites.
12. **`EXCHANGES[x].body_addr()` returns the address of the slot's storage.**
    - Site: `sawos/kernel/core/objects.saw:2149`. `body_addr` is `&var self`
      (`objects.saw:2031`) and returns a `UInt` address of the element's
      inline storage.
    - It must stay a place use (`borrow var EXCHANGES[x].body_addr()`), since
      under getitem it would return a copy's address. The address also
      outlives the borrow's extent.
    - The other three A3 sites are ordinary `&var self` calls on `TimerSlot`.
13. **"Looks like a copy, is a copy" moves the cost of field reads.**
    - Sites: sawos 410 G2 reads (`PROCESSES[p].state`, etc.), std 22
      (cbor/json level stacks), devtools 28.
    - Each becomes a whole-element getitem copy unless it is written
      `borrow let`. No perf measurement was taken here. For sawos (thread t1), keep the gate's per-image size diff on the migration patch as a budget, but it cannot show whether a given copy was folded: an extra memcpy or a larger stack slot can cost little image size, unrelated changes can grow or cancel it, and growth alone does not attribute cause to G2. Whether `-Oz` turns a whole-slot copy plus a one-field read into one load is answered by optimized IR or disassembly of representative G2 reads, with stack/frame evidence where relevant. The observable result is
      unchanged: no G2 chain calls a method that returns an address.
14. **`get` changes from an optional place to an optional value.**
    - Today `v.get(i)!.n += 10` writes in place: `probe_k_forced.saw` prints
      `v[1].n = 12`, and the std doc comments at `vector.saw:102` and
      `map.saw:275` say so.
    - Sites: 0 in the trees; 31 std `get` uses in the non-error examples
      (§D).
    - Every write, presence test or non-Copy chain through `get` has to move
      to `find`, or to `borrow`.
15. **Generic std bodies cannot use getitem.**
    - Sites: Map's probe paths (`match self.slots[idx]`, 7 sites) and
      `_key_ref(i)!.copy()` (4 sites).
    - They read places of abstract `MapSlot<K, V>` / `K` / `V`. getitem needs
      a Copy element, so each site needs `borrow let` (block form for the
      `match`).
16. **The largest non-kernel migration is the toml section reads.**
    - Sites: `doc.section_at(x).get("k") ?? ""`, repeated 18 times in blade
      (`manifest.saw:160-232`, `lock.saw:238-250`, `sosimg.saw:363, 373`) and
      16 times in `libs/toml/tests`.
    - `TomlSection` is NoCopy, so each becomes
      `borrow let doc.section_at(x).get("k") ?? ""`. Several sit inside
      `assert(...)` arguments. The rules admit this; it is flagged for volume.
17. **The sawos counts differ from the ones posted in t8.**

    | | t8 (lexical) | this survey (compiler) |
    |---|---|---|
    | place uses | 486 | 644 |
    | writes | 173 | 234 (196 field writes, 34 whole-slot stores, 4 mutating calls) |
    | roots | 10 | 13 |
    | files | 9 | 9 |

    A non-comment grep for `ROOT[` over `kernel/core/*.saw`, for the 13
    roots, also returns 644. The 13 roots are all the `unsafe static var …:
    Slab<…>` declarations: ATTACHMENTS, EVENTS, EXCHANGES, FREE_RANGES,
    INTERRUPTS, IOMEMORIES, MAPPINGS, MEMORIES, PIPES, PROCESSES, THREADS,
    TIMERS, WAITERS.

## Methodology

- **Instrument.** `probe_driver.py` / `probe_driver2.py` / `probe_driver3.py`
  (all under `.build/scratch/survey/`) import sawc and patch in-process. The
  compile runs `sawc.main()` unchanged and stops right after the first
  place-lowering pass, so there is no codegen.
  1. `place_uses._PlaceUses._window_call` records every window. Its caller
     function gives the shape: `_assignment`, `_chain_window`, `_span_call`,
     `_chain_assign_window`, `_borrow_match`, `_presence_condition` or
     `_borrow_operand_window`. The record also carries the element type, its
     `Namespace.copy_tier`, the window flavor, the root, the rendered key,
     and the enclosing statement (from patched `_stmt`/`_block`).
  2. `_rhs_names_root` records the DF-218j hoists.
  3. A census walks the checked ASTs handed to the place pass. It records
     `borrows` declarations with their compiler-recorded
     `place_receiver_mutation`, closure arguments whose resolved function type
     takes references (plus their `captures`), Map places with their parent
     context, `for` windows (`ForLoop.window`) with the effect-graph answer
     for the function and for each call in the body, and non-accessor index
     writes.
- **Entries compiled (52):**
  - blade `src/main.saw`, `src/test_simple.saw`, 24 `tests/*.saw` and 3
    fixtures (Blade's `--module-path` set from `tools/blade_bootstrap.py`).
  - libs: each `src/lib.saw -c` and 9 `tests/*.saw`.
  - devtools: irdet, bench, warehouse and 7 dogfood programs.
  - sawos `kernel/main.saw` for arm64 and riscv32. The flags come from
    `tools/sos_runner.py:5798-5812`: `--freestanding --no-hidden-alloc
    --runtime-provider -Oz --target … --module-path kcore/hal/imgformat/sosrt/sosabi`
    (`rv32core` for riscv32). Both arches give the identical 644 kernel sites.
  - The examples ran through `probe_run_examples.py`, which applies each
    file's `// COMPILE-FLAGS:` minus `--emit-*`.
  - std (all 33 files plus `builtin.saw`) is lowered in every hosted compile.
- **Coverage.** 87 of the 92 `.saw` files in std/blade/libs/devtools reached
  the place pass.
  - The 5 that did not are `devtools/dogfood/programs/w1_{chatroom,filesearch,limiter,mapreduce,pipeline}.saw`.
    They fail to typecheck on main, e.g.
    ``argument `ch0` expects `Channel<String>` but got `Result<Channel<String>, AllocError>` ``
    and ``type `Result` has no method `lock` `` (design 234's fallible
    constructors).
  - Those 5 were scanned with the parser only (`probe_ast_only.py`): 6
    `lock` closure calls and 4 fixed-array writes (not places).
  - Examples: 1,699 non-error files and 76 error tests reached the pass.
    3 XFAIL success pins (DF-257d, DF-252a, DF-259c) and 3 `EXPECT: docs`
    tests did not.
- **Dedup.** Sites are deduplicated on `(file, line, column, shape)` across
  entries. Generic instantiations (`is_mono_instance`) and compiler-synthesized
  declarations are skipped. The post-coroutine-transform lowering pass (frame
  `Slot.value()` lends) is excluded.
- **H verdicts** apply the ruled rules by hand: §2.2 early-close, §3 declared
  roots and §5.2 derivation. The compiler did not check them, since no
  compiler implements them.

## Limitations

- **Not covered at all:**
  - sawos outside `kernel/` (hal, rt, root, tests), per the brief.
  - Place uses in trait default bodies, static initializers and default
    parameter values. The place pass does not walk them either (it iterates
    functions, extension methods and inline modules).
  - Examples whose compile fails before place lowering (890 error tests).
- **D4 get-or-insert and I triples are heuristic.** D4 cannot see
  cross-statement insert patterns. The I triples were chosen by
  parameter-name/type filter plus reading.
- **J's detector.** It reads the effect graph's `frame_boundary` for user
  calls, std's `_std_suspending_methods_ignoring_closure_calls` name table
  and the builtin `_std_suspending_functions`. A call that suspends only
  conservatively (through a closure parameter or an existential dispatch) is
  not counted, so the 88 is a floor.
- **The E-345 check matches names.** It compares the receiver's root with the
  closure's recorded `captures` plus every identifier in its body. A root
  reached through an alias would be missed.
- **G2's "same spelling" holds only with a shared variant.** It assumes the
  accessor gets a `&self` variant (§5.2 derivation). For Vector.[] and
  Slab.[] this rests on the compiler-recorded `place_receiver_mutation = None`
  plus the shape probe, not on an implementation of §4.
