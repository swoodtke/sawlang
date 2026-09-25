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
- **A block is an expression** (Ruled). Its value is its tail, as with `if` and
  `match` blocks. The value must be owned or copied out. It can never carry the
  borrow itself: no reference, slice or borrowing struct into the place.
  ```saw
  let outcome = borrow var task = frames[i] {
      match task.resume() {
          case Pending -> Outcome(done: false, wake: task.wake_reason())
          case Ready -> Outcome(done: true, wake: Wake.None)
      }
  }
  ```

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
- **In argument position it passes the place by reference** (Ruled).
  `borrow var <place>` passes `&var`, and `borrow let <place>` passes `&`. The
  prefix replaces the `&`/`&var` sigil at that argument, and the borrow lasts
  for the call:
  ```saw
  bump(borrow var g[4])
  checksum(borrow let buf[4..])
  ```
  A local, or a field path with no `borrows` accessor in it, is still passed as
  `&x` / `&var s.field`. `borrow` is written only where a `borrows` accessor is
  called.

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

### 2.5 Suspension (Ruled: all borrows may span suspensions; Proposed: the lock exception)

Any borrow may stay open across a suspension: block form, statement form,
`for` (§2.6) and a borrowed argument alike. A borrow held across a suspension
lives in the coroutine frame like any other live value, and the borrow check is
suspension-aware (SL:architecture).

**Proposed exception: `sync` accessors, which today means locks.** A task can
resume on a different worker after a suspension. A lock held across one breaks
twice:
- The owner check misfires. The lock word records a thread (§8), so the release
  would come from a thread that is not the owner, and another task on the
  original worker would look like a re-entry.
- It can deadlock. A task spinning for the lock can occupy the worker the holder
  needs in order to resume.

So a lock accessor is declared `sync`, and the body of a borrow through it
cannot suspend. A lock that may be held across a suspension is a different type:
its owner is the task, and its waiters park rather than spin. It can be added
when something needs it.

### 2.6 `for` is a borrow scope (Ruled)

`for` is the repeating form of `borrow`, not a separate mechanism. In
`for x in v.iter() { … }`, the head `v.iter()` is borrowed for the whole loop,
exactly as a `borrow` block's head is. The body runs once per `next`, until
`next` returns `None`. The root charge follows §3 (shared for an `&self`
accessor), and the borrow may span suspensions (§2.5).

**Borrowing each element** (Proposed; codex, borrowing-survey t3). Today
`v.iter()` yields copies, so it works only for Copy elements. A loop over
NoCopy elements, like a vector of `Session`s, borrows each element in turn:

```saw
for borrow let s in sessions.iter() { print(s.name) }
for borrow var c in grid.cells() { c.weight += 1 }
```

- The iterator's `next` is itself an accessor:
  `func next(&var self) borrows -> &var T?`, or `&T?` for a shared iterator.
  Each iteration is one nested borrow, closed before the next `next`, so there is
  never more than one element lent at a time.
- The collection is charged for the whole loop, exclusively for `borrow var`, so
  the body cannot push to the vector it is walking.
- A plain `for x in …` copies each element and so needs Copy elements. The
  `borrow` keyword keeps the in-place form visible (§1). `for var x in …` would
  read as a mutable copy.

**Visitor APIs stay** (Ruled: "closure based visitor APIs must be allowed").
`each`, `each_indexed`, `map`, `fold`, `sort_by`, `Map.each`/`each_key`/
`each_value` and `Set.each` remain closure-based, in std and in user code. Their
closures' reference parameters and captures are ordinary MIR borrows (§9).
`for` is the alternative for plain iteration, not a replacement. `sort_by`'s
internals lend two elements of one root at once, which is the `unsafe` tuple
lend of §7.

### 2.7 Passing a borrow onward (Ruled)

- **A bound place can be passed on.** Inside a borrow, `f(&var slot)` hands the
  place to a callee as an ordinary reborrow for the duration of the call.
- **A lend can forward another accessor's place** (Ruled: "forwarding a borrowed
  reference via a function call is allowed"). Inside a `borrows` body, `lend`
  may name a place reached through another accessor. `lend` is already the
  explicit borrow marker inside an accessor, so its own operand needs no
  `borrow` keyword:
  ```saw
  lend self.sections[i]                                   // toml's section_at
  ```
  The inner borrow opens for as long as the outer lend is open, nested inside
  it, and closes in reverse order.
- **Only the `lend` operand is exempt.** A place reached some other way is an
  ordinary borrow and is written as one (codex t16). A plain `self.slots[b]` is
  a getitem: refused for a NoCopy or generic slot, and for a Copy slot it
  matches a copy, not the map's storage. So Map's `find` opens a borrow of the
  slot, matches the bound place, and lends its payload:
  ```saw
  borrow var slot = self.slots[b] {
      match slot {
          case Occupied(_, v) -> { lend v }
          …
      }
  }
  ```
  A `lend` inside a `borrow` block keeps that block's borrow open for as long as
  the outer lend is open, exactly as a forwarded operand does.
- **Forwarding keeps a `sync` restriction** (Proposed, with the lock exception
  of §2.5; codex t17). An accessor whose lend forwards a `sync` accessor's
  place, such as one that lends through `mutex.lock()`, must itself be declared
  `sync`. Otherwise it is refused. The suspension that would break the lock
  happens in the *consumer's* body while the accessor is paused at `lend`. So
  the ordinary rule that a `sync` function cannot call a suspending one does not
  catch it, and the restriction has to travel with the declaration.

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
- **An accessor may lend a borrowing struct** instead of a reference, such as
  an iterator (`(&self) borrows -> VectorIterator<T, A>`). The same rule
  charges its root: shared for `&self`, exclusive for `&var self`. It may be
  called only as a `borrow` head or a `for` head (§2.6), and the struct cannot
  leave that scope.
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

**When the two bodies differ, both are written** (Ruled: "if there are
differences between the exclusive and shared borrow implementations, they must
be explicitly defined"). `@synthesize(shared)` applies only when the same body
is valid under both signatures. There is no mode test inside one body, like
today's `#lend_var`. `Data` is the case: its exclusive `[]` must separate shared
copy-on-write storage before lending, and its shared `[]` must not.

```saw
extension Data {
    public func [](&self, index: Int) unsafe borrows -> &UInt8 {
        self.check_index(index)
        lend (self.byte_ptr() as UnsafePointer<UInt8>)[index]
    }
    public func [](&var self, index: Int) unsafe borrows -> &var UInt8 {
        self.check_index(index)
        if not self._make_ready(self.length) {    // separate shared bytes before a write
            panic("Data.[]: allocation failed")
        }
        lend (self.byte_ptr() as UnsafePointer<UInt8>)[index]
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

`Map` declares its getitem and setitem explicitly, because it inserts.

**Field reads of a derived getitem** (Ruled). Under "looks like a copy, is a
copy", `PROCESSES[p].state` is a getitem of the whole element followed by a
field read. When getitem is *derived* from a shared place accessor, the compiler
may lower `v[i].f` as a shared borrow plus a copy of `f` alone, **but only when
copying the element runs no code**: no declared `copy()` hook and no deinit
anywhere in it, so the copy is a plain memory copy. Being Copy-tier is not
enough (codex t15). A declared `copy()` is an executable retain hook, and its
deinit is the release. Skipping the whole-element copy would skip both, and a
hook that counts copies would see the difference. Under that restriction the
lowering is observably identical, so it is an allowed optimisation, not a
language rule. sawos's slab elements qualify. A *declared* getitem is always
called as written, since its body may have side effects. (Evidence for sawos's 410 such reads comes from the IR,
not from a size delta alone: borrowing-survey K13.)

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

On a miss, the read form yields the default and the other forms insert it.
The read and compound forms are plain value code for Copy values, with no
`borrow` written.

**The default is lazy** (Ruled: "Python's eager evaluation has bit me in the
past, so i think lazy defaults are the more expected behaviour"). The default
expression is evaluated only when the key is absent, never on a hit. Eager
evaluation is a silent bug in exactly the shapes that matter:
- `borrow let id = ids[name, default: next_id()]` would burn an id on every
  lookup;
- `cache[k, default: try load(k)]` would do I/O, and could fail, on every hit.

**The mechanism** (Proposed; the lead and the Air independently, refined per
codex t4): `default:` is a compiler-known argument label with `??` semantics,
not a general lazy-parameter feature. There is no new parameter kind and no
closure, so nothing is captured or allocated.

**The protocol is one declared trait** (Ruled: "one KeyedPlace trait for
now"), not a method name the compiler guesses:

```saw
trait KeyedPlace<K, V> {
    func find(&var self, key: &K) borrows -> &var V?              // the existing entry, if any
    func insert(&var self, key: K, value: V) borrows -> &var V    // store, then lend what was stored
}
```

- The read, compound and place forms are built from these two operations.
  There is no second, value-level trait: the value forms are the place forms
  plus a copy. The pure store (below) is not a `KeyedPlace` operation. It needs
  the type's ordinary setter, `[]=`, so a generic `KeyedPlace<K, V>` bound alone
  does not allow it (codex t4).
- **A read holds the root shared when it can.** It borrows through `find`'s
  `&self` twin when the conformer has one, written or `@synthesize(shared)`
  (§4), and otherwise through the exclusive `find`, following §4's
  least-privilege rule. `Map` synthesizes the twin.
- **Keys are never silently duplicated.** `find` takes the key by reference
  (`&K`). `insert`, the one operation that stores, takes it by value as the
  key's *last* use. The saved key is therefore borrowed, then moved once, and
  never copied behind the reader's back.
- The value forms (read, compound assignment) need a Copy-tier `V`, following
  "if it looks like a copy, it copies". For a NoCopy `V`, write the place form.

**Per-role meaning.** The receiver and key are always evaluated exactly once,
first:

| Spelling | Meaning | When `e` is evaluated |
|---|---|---|
| `m[k, default: e]` (read) | `find(&k)`: on a hit, copy the entry out; on a miss, yield `e`. Nothing is inserted | only on a miss |
| `m[k, default: e] op= r` | evaluate `r`, then `find(&k)`; on a miss, evaluate `e` and `insert(k, e)`, which moves `k`; then `entry op= r` in place | only on a miss. The *result* is stored, so `counts[k, default: 0] += 1` stores `1` on a miss |
| `m[k, default: e] = v` | `m[k] = v`, the type's own setitem; requires `[]=` | **never**. A pure store ignores the default; writing one there draws a `-W` warning |
| `borrow var x = m[k, default: e] { … }` | `find(&k)`; on a miss, evaluate `e` and lend `insert(k, e)`, which moves `k` | only on a miss |

- The compound form evaluates `r` before the borrow opens, as every assignment
  does (§2.2), so `r` may read the map. On a miss, `e` runs where `find` lent
  nothing, so it may read the map too (§2.4).
- The place form always works on storage in the map, never on a temporary that
  is written back later. That would behave differently, for example if the body
  reads the map's length. It needs no second lookup after inserting.
- A user-defined type gets `default:` by conforming to `KeyedPlace`, which
  states exactly which of its operations are used.
- Missing keys are handled per call. A default parameter value on the getter
  would silently undo the missing-key panic, so there is none. A per-instance
  default (`defaultdict`) could be library sugar later.

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
  They become `borrow var g[4].weight += 1`, `bump(borrow var g[4])` (§2.2) and
  `borrow var m.find(k)?.field = v`.
- Use-site inference of shared versus exclusive (designs 141 and 146).
- A mode test inside one accessor body (`#lend_var`); differing bodies are
  written as two accessors (§4).
- `Map.[]` returning an optional.
- **The stdlib's closure-based borrowing APIs** (`with_ref`, `with_var_ref`,
  `Mutex.lock` taking a closure, `Arc.with_unique`) become `borrows` accessors.
  (Ruled: yes for the stdlib.) The visitor APIs (`each`, `map`, `fold`,
  `sort_by`, …) are not in this list. They stay (§2.6).
- **User code may still hand references to closures.** A non-escaping closure
  that captures a reference, or receives one, stays a language feature, and
  nothing forbids a user library from offering a closure-based API. (Ruled: "no
  to userspace not being able to use closures for refs (if they want)".)
  Consequence for the compiler: a closure's reference captures are explicit
  borrows in the MIR, charged against their roots for as long as the closure
  can run. The one borrow check sees them like any other borrow, so the SL-345
  class is handled structurally, not by a separate capture analysis that
  enumerates capture spellings.

### 9.1 Migration notes (from SL:borrow-survey §K)

The survey's other flagged items are consequences of the rules above, not gaps
in them. Each note says what the migrated code looks like.

- **`m[k]! = v` changes meaning (K7).** Today the `!` panics on an absent key.
  `m[k] = v` is setitem and inserts. Code that relies on the panic writes the
  place form, `borrow var e = m[k] { e = v }`, whose `[]` panics on absence
  like getitem.
- **Presence tests on NoCopy values (K8).** `if let _ = m["zz"]` has no value
  form, since `get` would have to copy. Use `m.contains_key(k)` on a `Map`.
  Elsewhere, a `find` block yields the answer as a value (§2.1):
  `let present = borrow let e = c.find(k) { if let _ = e { true } else { false } }`.
- **"Did it write" through a conditional lend (K9)** (Proposed). The statement
  form with `?` has type `Void?`, as optional-chain assignment does today, so
  `guard let _ = borrow var m.find(k)?.value = 7 else { … }` stays one line.
- **Lock re-entry by the same name (K10).** `examples/spinlock_basic.saw` pins
  "`try_lock` inside a critical section refuses rather than deadlocking". Under
  §8 that is a compile error, so the pin becomes an `@test(refuses: …)` case,
  and the runtime panic is pinned through two names for one lock.
- **An address out of a slot (K12).** `EXCHANGES[x].body_addr()` stays a place
  use, `borrow var EXCHANGES[x].body_addr()`, because a getitem copy's address
  would be wrong. The returned `UInt` outlives the borrow, which is the unsafe
  author's obligation (§8a).
- **`get` returns an optional value, not a place (K14).** `v.get(i)!.n += 10`
  wrote in place, and through a value `get` it would change only a copy.
  Writes, presence tests and NoCopy chains through `get` move to `find` or
  `borrow`.
- **Generic std bodies (K15).** Map's probe paths read places of abstract `K`,
  `V` and `MapSlot<K, V>`, which getitem cannot copy. They use `borrow let`,
  with the block form for a `match`.
- **toml section reads (K16).** Each `doc.section_at(x).get("k") ?? ""`
  becomes `borrow let doc.section_at(x).get("k") ?? ""`. This is admitted as
  is and flagged only for volume (34 sites).

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

- **Survey: done** (SL:borrow-survey). Its seven design gaps are settled in
  this revision: K1 (§4), K2 (§2.7), K3 and K4 (§2.6, §3), K5 (§2.1), K6
  (§2.2) and K13 (§5.2). §8a settles K11, and §9.1 covers the rest.
- **Still Proposed:** several bindings (§2.3), path-sensitivity (§2.4), the
  lock exception to suspension (§2.5) and the `sync` requirement it puts on
  forwarding (§2.7), `for borrow let|var` for per-element
  borrows (§2.6), separate subscript methods (§5.2), and the `Void?` statement
  form (§9.1, K9).
- (Settled: `default:` is lazy (§5.4); static roots are the unsafe author's
  obligation, with an optional warning (§8a).)
