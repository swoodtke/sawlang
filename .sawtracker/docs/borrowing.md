# Borrowing, subscripts and slices

Part of the language lockdown that precedes the self-hosted compiler. The Python
compiler is frozen, so this describes the language that compiler will
implement, not what `sawc` does today.

Each decision below is marked **Ruled** (the user decided), **Proposed** (the
lead's recommendation, not yet ruled), or **Deferred**. Everything was decided
in conversation on Sep 24 2026.

## 1. Principles

- **A reader can tell a copy from a borrow by looking.** Anything that touches
  storage in place says `borrow`. Anything that looks like a copy is a copy.
  (Ruled: "if it looks like a copy, then just copy".)
- **Modes are declared, never inferred.** Whether a borrow is shared or
  exclusive is read from declarations, not from how the code happens to use a
  place. (Ruled.)
- **One construct, no hidden windows.** A `borrows` function can be called only
  through the `borrow` construct. The inline place uses of today's language
  (`g[4].weight += 1`, `bump(&var g[4])`, `m[k]?.field = v`) are gone. (Ruled:
  this "eliminates any confusion a user might have about what exactly is
  happening by just reading the code".)

## 2. The `borrow` construct

### 2.1 Block form (Ruled)

```saw
borrow var slot = v[i] { slot.count += 1 }
borrow let entry = doc.section("net") { print(entry.name) }
borrow var n = counter.lock() { n += 1 }
```

- `borrow let` gives a read-only place; `borrow var` gives a writable one.
- The binding is always named. Inside the block, only the name reaches the
  place. The head expression (`v[i]`) cannot be used there, so the place the
  body works on is always the one that was borrowed.
- The head is evaluated once and may be any expression, calls included
  (`v[next_index()]`, `counter.lock()`).
- There is no `else` clause. The binding carries whatever the accessor lends:
  a conditional lend binds an optional place, and the body discriminates it with
  `if let` or `match` (§2.4).

### 2.2 Statement form (Ruled)

For in-place work that fits in one statement, `borrow` prefixes the place
directly, and the borrow lasts exactly that statement:

```saw
borrow var grid[r][c].weight += bias
borrow var queues[k].push(job)
print(borrow let doc.section("net").name)
```

- The prefix covers the place expression up to and including its `borrows`
  call. What follows (`.weight`, `.push(job)`) acts on the lent place.
- A chain with several `borrows` calls (`grid[r][c]`) is a chain of nested
  reborrows, exactly like §2.3's `borrow var row = grid[r], var cell = row[c]`:
  the root is charged first, then each reborrow, and they close in reverse at
  the end of the statement. The statement form has no semantics of its own
  beyond the block form's.
- Several borrows in one statement are checked together, so
  `borrow var a[i].x = borrow let b[j].x` is fine.
- **A borrow whose result is only copied closes as soon as the value is read**
  (Ruled: "if it can be copied, then yes"). The right side of an assignment is
  evaluated before the left side's borrow opens, so
  `borrow var v[i].x = borrow let v[j].x` works when `x` is copyable: the right
  borrow opens, `x` is copied out, the right borrow closes, and only then does
  the left borrow open. Two borrows are live together only when both are still
  in use.
- A conditional lend used inline needs `!` (panic if absent) or `?` (skip if
  absent), since there is no block in which to discriminate it.

### 2.3 Several bindings (Proposed)

```saw
borrow var row = grid[r], var cell = row[c] { cell.weight += bias }
```

- Bindings open left to right. They close in reverse order on every exit:
  falling off the end, `return`, `break` or `continue` out of the block, and a
  propagating `try`.
- A later binding may borrow through an earlier one. That freezes the earlier
  binding while the later one is live (an ordinary reborrow).

### 2.4 Conditional lends (Ruled: no `else`; Proposed: path-sensitivity)

An accessor declared `borrows -> &var V?` lends an optional place:

```saw
borrow var e = m.find(k) {
    if let entry = e { entry.count += 1 }
    else { m.insert(k, Entry(count: 1)) }   // see below
}
```

On the absent path no borrow was ever opened, so touching the root there is
sound. **Proposed:** the borrow checker is path-sensitive on the MIR control-flow
graph and knows that an absent arm of the binding holds no borrow. The common
get-or-insert case does not need this, because the `default:` subscript (§5.4)
covers it.

### 2.5 Suspension (Proposed)

A borrow may stay open across a suspension unless its accessor is `sync`. A
lock accessor is `sync`, so a lock body cannot suspend. The machinery for a
borrow held across a suspension already exists.

## 3. Declared modes and the root charge (Ruled)

Two independent facts, both read from the accessor's declaration:

- **The binding keyword is a capability on the place.** `let` means the body
  only reads the place, and is always allowed. `var` means the body may write
  it, and requires a `&var` lend.
- **The root charge follows the declaration.** A root is held EXCLUSIVELY for
  the whole borrow if the accessor takes `&var self` or lends `&var T`. It is
  held shared only for `(&self) borrows -> &T`.

| Declaration | `borrow let` | `borrow var` | Root |
|---|---|---|---|
| `(&self) borrows -> &T` | read-only place | error: the lend is read-only | shared |
| `(&var self) borrows -> &T` | read-only place | error: the lend is read-only | exclusive |
| `(&var self) borrows -> &var T` | read-only place | writable place | exclusive |
| `(&self) borrows -> &var T` (cell-carrying types only, e.g. `Mutex.lock`) | read-only place | writable place | exclusive |

- Under a shared root, other shared reads of the root are allowed. Under an
  exclusive root, the body cannot touch the root at all.
- **Why it is declarative:** an exclusive accessor narrowed to "shared" at the
  use site is unsound when its prologue or epilogue writes `self`, because two
  paused accessor frames would each hold `&var self`. This retires the
  use-site mode inference of designs 141 and 146.

## 4. `@synthesize(shared)` (Ruled)

`@synthesize(shared)` on a `(&var self) borrows -> &var T` accessor derives the
`(&self) borrows -> &T` twin. It works by typechecking the same body again
under the shared signature. If the body writes `self`, the synthesis is refused
by the ordinary type error, so there is no separate "does it mutate?" analysis.

`borrow let` picks the `&self` variant when one exists, the least privilege
that works. Otherwise it uses the exclusive accessor, and the root is exclusive.

```saw
extension Vector<T> {
    @synthesize(shared)
    public func [](&var self, i: Int) borrows -> &var T {
        if i < 0 || i >= self.len() { panic("index out of range") }
        lend self.buffer[i]
    }
}
```

## 5. Subscripts

### 5.1 Three roles (Ruled)

| Role | Declared as | Used as | Meaning |
|---|---|---|---|
| getitem | `func [](&self, key: K) -> V` | `m[k]` | copy the value out; panics if absent |
| setitem | `func []=(&var self, key: K, value: V)` | `m[k] = v` | store: insert or replace (Map), replace (Vector, panics out of range) |
| place | `func [](…) borrows -> &var V` | `borrow var e = m[k] { … }` | lend the storage in place |

- Plain subscripts are values and `borrow` subscripts are places; the spelling
  at the call site picks the role.
- `counts[k] += 1` is getitem then setitem, and panics if `k` is absent. The
  receiver and every key expression are evaluated exactly once, even though
  getitem and setitem are two calls, so `counts[next_key()] += 1` calls
  `next_key()` once. The new compiler gets this by construction from MIR
  temporaries. (SL-368 needed the same rule for receivers reached through a
  pointer index or a call.)
- `Map`'s getitem panics on a missing key, consistent with `Vector` and with
  the direct-accessor rule. `m.get(k)` is the optional form. (Ruled: the user
  "really dislike[s] the map's [] operator returning an optional".)
- An optional *place* is a named accessor such as `m.find(k)` lending
  `&var V?`, because `[]` in a `borrow` panics on absence, like getitem.

### 5.2 Declaration form (Proposed)

Separate methods, not a `subscript { get set borrow }` block. Every role is an
ordinary method, so its receiver mode, effects, visibility, overloads, doc
comment and `@synthesize` apply unchanged, and the compiler has one less
special form. The block form could be added later as sugar.

**Derivation.** If a type declares only the place accessor, getitem and setitem
are derived:
- getitem is a shared lend plus a copy. It applies to Copy-tier values only,
  and only from a `&self` place accessor (declared or `@synthesize(shared)`),
  so a plain read never locks the root exclusively or runs a prologue that
  writes `self`.
- setitem is an exclusive lend plus an assignment (replace).

`Map` declares its getitem, setitem and `default:` pair explicitly, because it
inserts.

### 5.3 Multi-argument subscripts (Ruled)

```saw
extension Matrix {
    func [](&self, row: Int, col: Int) -> Float
    func []=(&var self, row: Int, col: Int, value: Float)
    func [](&var self, row: Int, col: Int) borrows -> &var Float
}
```

- Arguments follow the ordinary call rules, labels included.
- The setter's `value` is its last parameter, so `m[r, c] = x` calls
  `[]=(r, c, value: x)`.
- **Family consistency:** for one family, the key parameter lists of `[]`, of
  `[]=` without its `value`, and of the place accessor must match, and
  `value`'s type must equal the getter's return type.
- `m[r, c]` (two arguments) and `m[(r, c)]` (one tuple argument) are different
  signatures.

### 5.4 The `default:` subscript (Ruled)

```saw
counts[word, default: 0] += 1
if names[id, default: ""] == "admin" { … }
borrow var e = sessions[id, default: Session()] { e.hits += 1 }
```

A getitem/setitem pair: the getter returns `m.get(k) ?? default`, and the
setter inserts. It is plain value code for Copy values, with no borrow.

**The default is lazy** (Ruled: "Python's eager evaluation has bit me in the
past, so i think lazy defaults are the more expected behaviour"). The default
expression is evaluated only when the key is absent, never on a hit. Eager
evaluation is a silent bug in exactly the shapes that matter:
- `borrow let id = ids[name, default: next_id()]` would burn an id on every
  lookup;
- `cache[k, default: try load(k)]` would do I/O, and could fail, on every hit.

**The mechanism** (Proposed by the lead and the Air, independently): `default:`
is a compiler-known argument label with `??` semantics, not a general
lazy-parameter feature. `m[k, default: e]` is defined as `m.get(k) ?? e`. On the
setter and place side, `e` is inserted only on a miss. There is no new
parameter kind and no closure, so nothing is captured or allocated, and
laziness stays confined to the one spelling whose reading already promises it.
The cost: a user-defined subscript family gets the lazy behaviour by declaring
the same `default:` shape.

The **place** overload, `borrow var e = m[k, default: v] { … }`, is a third
accessor with its own meaning: on a miss it *inserts* `v` into the map, then
lends the stored entry under an exclusive root. The body therefore always works
on storage in the map. It never works on an owned fallback temporary that is
written back later, which would behave differently (for example, if the body
reads the map's length). Missing
keys are handled per call. A default parameter value on the getter would
silently undo the missing-key panic, so there is none. A per-instance default
(`defaultdict`) could be library sugar later.

## 6. Slices (Ruled)

- **Type.** `&[T]` and `&var [T]` are reference-like. They appear only as
  parameters and `borrow` bindings, and are never stored in a field or returned.
  Their representation is a pointer and a length.
- **Views go through `borrow`, like every other place.**
  `borrow let header = packet[0..20] { parse(header) }`, or the statement form
  at a call site: `checksum(borrow let buf[4..])`. A range subscript is a
  `borrows` call, so there is no exception for slices. `&buf[4..]` is refused,
  as `bump(&var g[4])` is, with a hint naming the `borrow let` form.
- **A view is not a copy.** `borrow let s = buf[4..]` is a view into `buf`. A
  plain `buf[4..]` follows the copy rules below and produces an owned value;
  to pass a reference to such a copy, bind it first (`let c = buf[4..].copy()`,
  then `f(&c)`).
- **Whole containers coerce.** Passing `&v` where `&[T]` is expected works for
  a whole `Vector`, `[T; N]` or `Data`.
- **Copies follow the parent's copy policy.**
  - `let h = vec[0..20]` is refused for an ExplicitCopy parent (`Vector`):
    write `.copy()` for an owned copy, or `borrow` for a view.
  - A Copy-tier refcounted parent (`Data`, `String`) copies implicitly. The
    copy shares the parent's storage as an offset and length, so it is O(1).
    The known cost: a small slice keeps a large parent buffer alive.
  - Slicing a fixed array with a runtime range copies to a `Vector`, so it is
    ExplicitCopy.
- **Strings** are byte-indexed and panic if a cut lands inside a UTF-8
  character.
- **Access.** `s[i]` panics out of range and `s.get(i)` is optional. `&var [T]`
  allows element writes, `swap`, `sort` and `fill`, but never `push`: a
  borrowed range cannot grow. An extern call receives a pointer and a length.
  Holding a slice across a suspension is an ordinary borrow.

## 7. Lending several places at once (Ruled)

A `borrows` accessor may lend a tuple of places, under one exclusive root
charge:

```saw
extension Vector<T> {
    func split_at(&var self, k: Int) borrows -> (&var [T], &var [T]) {
        lend (self.buffer[0..k], self.buffer[k..self.len()])
    }
    func pair(&var self, i: Int, j: Int) borrows -> (&var T, &var T) {
        if i == j { panic("pair: the same index twice") }
        lend (self.buffer[i], self.buffer[j])
    }
}

borrow var (left, right) = v.split_at(mid) { merge(&var left, &var right) }
```

**The safety boundary.** One exclusive root charge keeps *outside* accesses out.
It does not prove the lent places are disjoint from *each other*, so:
- A safe accessor may lend a tuple only of places the compiler proves disjoint:
  distinct fields, or distinct constant indices of a fixed array.
- **The escape valve is an `unsafe` accessor** (Ruled: "unsafe requires the user
  to enforce the safety"). An accessor declared `unsafe`, in the effect slot
  beside `borrows`, may lend a tuple of places the compiler cannot prove
  disjoint, such as index- or range-based places. Its author enforces
  disjointness under Saw's existing unsafe rule: an unsafe function whose
  parameters are all safe types must be sound for *every* input, so it checks
  what it relies on, and a precondition it cannot check is spelled as an
  unsafe-typed parameter. Callers need no ceremony. It is available to user code,
  not only the stdlib:
  ```saw
  extension Grid {
      func cells(&var self, a: Int, b: Int) unsafe borrows -> (&var Cell, &var Cell) {
          if a == b { panic("cells: the same cell twice") }
          lend (self.slots[a], self.slots[b])
      }
  }
  ```
- The stdlib's `split_at` and `pair` are instances: `split_at` is disjoint by
  construction, and `pair` panics when `i == j`.
- Without `unsafe`, declaring `borrows` confers no such trust. A non-`unsafe`
  accessor that lends `buffer[i]` and `buffer[j]` together is refused, because
  the compiler cannot prove them disjoint.

## 8. Locks (Ruled)

- **No recursive locks.** A re-entrant lock would hand out two live `&var T`
  to one payload.
- **Re-entry through the same name is a compile error.** `Mutex.lock` lends
  `&var T`, so the mutex is held exclusively for the borrow, and a second
  `m.lock()` in its own body is refused.
- **Re-entry through another name panics at runtime**, for example through two
  `Arc` clones of the same mutex. The lock keeps the one-word lock that is
  unlocked at zero, and gains error-checking semantics in that word:
  - macOS `os_unfair_lock` already stores its owner and traps on re-entry;
  - on Linux the futex word holds the owner's thread id (the PI-futex
    convention), and `acquire` panics when it sees its own.
  - `pthread_mutex_t` with `PTHREAD_MUTEX_ERRORCHECK` was considered and
    rejected. It is 40–64 bytes, has a nonzero static initialiser on Darwin,
    and does not exist on freestanding targets.
- The runtime contract: re-acquiring a held lock must fail loudly and never
  deadlock, on freestanding runtimes too.
- **Why lock bodies must be `sync` (§2.5).** A task can resume on a different
  worker after a suspension, so a lock held across one would be released by a
  thread that is not its owner, and the owner check would misfire. `sync` on
  lock accessors is what makes the owner check sound, not only a frame
  convenience.
- **Freestanding owners need a seam.** There is no thread id to store on a
  freestanding runtime, so the contract needs a runtime seam answering "who
  holds this?". For a kernel, that identity is the CPU/hart id plus interrupt
  context, because the re-entry that matters is an interrupt handler taking a
  lock its own core already holds (sawos's irq.saw anticipates an
  `IntrSpinLock`). sawos is a `--runtime-provider` and implements the seams
  itself, so the seam's signature goes into rt/ABI.md before the contract lands.
  Providers then get a checked signature rather than a gap they discover at
  their first lock.

## 8a. Borrows rooted in an `unsafe static var` (Ruled)

The compiler checks exclusivity inside one function. A static is reachable from
any callee with no argument passed, so a borrow of a static cannot see a second
borrow taken by a function it calls:

```saw
unsafe static var PROCESSES: Slab<Process> = …

func exit_process(p: Int) unsafe {
    borrow var proc = PROCESSES[p] {
        proc.state = State.Exiting
        release_handles(p)            // inside: borrow var PROCESSES[p].refs -= 1
        proc.state = State.Dead       // two live `&var` into one slot
    }
}
```

**Ruled: the unsafe author's obligation.** ("Unsafe is unsafe and up to the user
to validate safety.")
- An `unsafe static var` is unsafe by declaration. Every function that touches
  one is already declared `unsafe`, and its author owns soundness (designs 130
  and 149).
- For a borrow rooted in such a static, in either form, that obligation
  explicitly includes this: no other access to the same place may happen while
  the borrow is open. That covers callees, other harts, interrupt handlers,
  indirect calls and extern code.
- The block form widens the window the obligation covers, compared with a
  single statement.
- **An optional warning, off by default** (`-W` category): the compiler can
  flag a direct call, inside a borrow of static `S`, to a function that
  transitively touches `S`. That catches the common same-thread mistake above.
  It is a hint, never a guarantee: it cannot see indirect calls, other harts,
  interrupts or extern code.
- **The safe path** for shared state that should be checked is a `static`
  wrapped in `SpinLock` or `Mutex`. Borrowing through its lock is exclusive at
  compile time, the lock excludes other harts at runtime, and re-entry panics
  (§8).

## 9. Retired from today's language

- Inline place use: `g[4].weight += 1`, `bump(&var g[4])`, `m[k]?.field = v`.
- Use-site inference of shared versus exclusive (designs 141 and 146).
- `Map.[]` returning an optional.
- **The stdlib's closure-based borrowing APIs** (`with_ref`, `with_var_ref`,
  `Mutex.lock` taking a closure, `Arc.with_unique`) become `borrows` accessors.
  (Ruled: yes for the stdlib.)
- **User code may still hand references to closures.** A non-escaping closure
  that captures a reference, or receives one, stays a language feature, and
  nothing forbids a user library from offering a closure-based API. (Ruled: "no
  to userspace not being able to use closures for refs (if they want)".)
  Consequence for the compiler: a closure's reference captures are explicit
  borrows in the MIR, charged against their roots for as long as the closure
  can run. The one borrow check sees them like any other borrow, so the SL-345
  class is handled structurally, not by a separate capture analysis that
  enumerates capture spellings.

## 10. Deferred

- Computed properties (`var area: Int { get set borrow }`). They are additive,
  so settle the field and property namespace when they are added.
- The `subscript { get set borrow }` block, as sugar over §5.2.
- A per-instance map default (`defaultdict`).
- `errdefer` and a library `Undo` guard. The library shape, if it is ever
  needed: a NoCopy struct holding the undo closure, whose deinit runs it, plus
  a `consumes func keep()` that ends it without running it. Its limits: the
  closure escapes, so it cannot capture references; it allocates; and a
  forgotten `keep()` rolls back on success.

## 11. Open

- **Survey: approved** (Ruled: "yes"). The Air runs a read-only survey of every
  current place use and closure-borrow call across sawc/std, blade, libs,
  devtools and sawos, classified by the form each becomes, with the awkward
  shapes flagged. sawos's numbers are already in (borrowing t8): one accessor,
  `Slab.[]`, used in 502 places.
- (Settled: `default:` is lazy (§5.4); static roots are the unsafe author's
  obligation, with an optional warning (§8a).)
