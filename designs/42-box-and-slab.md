# Design Brief 42 — Box<T, A> and the slab allocator: the kernel idiom end to end

**Status: LANDED.** `std/box.saw` (`Box<T, A: Allocator = Global>`, NoCopy, static
factories `make`/`make_or`, placement-move construction, `__deinit_in_place` +
`A().dealloc` teardown, payload method forwarding + `value()`) and `std/slab.saw`
(`SlabHead` + `slab_alloc`/`slab_dealloc`, lock-free CAS bump + LIFO free-list over
a caller `static` region) ship. The kernel idiom `Box<Job, JobSlab>` works end to
end (allocate to exhaustion → `Err`, scope-death reclaim, re-allocate). Full suite
green, zero xfails; verified `--freestanding` (region in `.bss`, no libc added).
Factory surface chosen: **static methods** on the struct (`Box<T>.make(v)` /
`.make_or(v)`) — the brief-28 static-factory path. Enabling compiler work:
conditional-move **drop flags** (fixed a pre-existing leak so `make_or`'s failure
path drops the un-moved value cleanly), `&T`→pointer / pointer↔`Int` casts,
writable `.bss` for bare-declared statics, and static-factory param-type
substitution. Deferred (per paper 19): the `AllocatedBy<Slab>` per-type sugar.

**Source:** tracker F3 (paper 19 stage-4 tail) + paper 19's "kernel
idiom" (`type TaskBox = Box<Task, TaskSlab>`). Every prerequisite has
landed: placement-write contract + alignof (28), allocator type params
with defaults (37), statics + Atomic<Int> (41), __deinit_in_place (17),
payload method forwarding (Arc, 21b), fallible factories (28), the D4
discussion's MakeBox mechanism (recorded in design 19's header).
**Exit criteria:** `Box<Task, TaskSlab>` works end to end over a static
slab region including exhaustion → Err; hosted `Box<T>` (Global
default) works; full suite green; zero xfails.

## Items

### 1. `Box<T, A: Allocator = Global>`
`struct Box<T, A: Allocator = Global> { ptr: UnsafePointer<T> }` in a
new std/box.saw. NoCopy. Construction via the D4-pinned mechanism:
- `MakeBox(value: T) -> Box<T, A>` — infallible tier: on allocator
  None, panic ("allocation failed") per the decided three-tier model.
- `MakeBoxOr(value: T) -> Result<Box<T, A>, AllocError>` — fallible
  tier; on failure the value is cleanly deinit'd by scope exit (the
  decided semantics; verify with a deinit-printing type) and the Err
  carries size/align.
  (Naming: static methods on Box or free functions — pick what the
  generics machinery supports cleanly; `Box<Int>.make(v)` via the
  brief-28 static-factory path is acceptable; report the surface
  chosen.)
Mechanism inside: alloc via `A()`, `ptr[0] = move value` (the
placement-move primitive — cite the contract comment), wrap. Deinit:
`__deinit_in_place(self.ptr)` then `A().dealloc(...)` with
sizeof/alignof. Payload access: method forwarding like Arc (probe how
Arc's forwarding is keyed and reuse; plus a `value()`/read accessor
for `T: Copy`). Tests: hosted Box<Int> (make, read, deinit),
Box<String> refcount-correct (deinit oracle), Box of a Deinit struct
(payload deinit exactly once), MakeBoxOr success + failure paths.

### 2. Slab machinery (std/slab.saw)
Freestanding-compatible (no libc) fixed-chunk allocator helpers over a
caller-owned static region: initialization-free LIFO free-list or
CAS-bump + free-list — using Atomic<Int> CAS/fetch_add (brief 41).
Shape: free functions taking (region: UnsafePointer<Int8>, region_len,
chunk_size, chunk_align, head: &Atomic<Int>) or a lean generic helper
struct — pick the shape that lets a USER unit struct wire its own
statics in ~10 lines; document the pattern. Alloc returns None on
exhaustion (feeding the three-tier model); dealloc pushes the chunk
back. Thread-safety: CAS loop (the Atomic exists; ABA is acceptable at
this stage — note it honestly in a comment).

### 3. The kernel idiom, proven
Test reproducing paper 19's idiom: `struct Task {...}`,
`struct TaskSlab {}` + `extension TaskSlab: Allocator` over a static
zero-init region (brief 41 BSS arrays) sized for N tasks;
`Box<Task, TaskSlab>` allocated to exhaustion — N successes then
`MakeBoxOr` → Err; dealloc (scope death) returns chunks — allocate
again succeeds. Also: `Vector<Int8, TaskSlab>`-style use is NOT
expected to work well (variable sizes vs fixed chunks) — do not force
it; Box is the slab consumer.

### 4. Freestanding probe
Cross-triple object emission of a core+alloc slab/Box program under
--freestanding (brief-20/41 probe style): no libc references; region
in .bss. Report the objdump evidence.

### 5. Docs
LANGUAGE_SPEC.md: Box section + slab pattern; paper 19 F3/stage-4
annotated fully landed (slabs done; AllocatedBy sugar stays deferred
per the paper). CLAUDE.md stdlib line.

## Hazards
Double-free/leak family on Box (deinit oracle, -O0 spot checks); the
placement-write live-vs-uninitialized line (MakeBox writes
uninitialized chunks — correct side; Box deinit releases live payload).
The slab's CAS loop under the two-thread test from brief 41's pattern
if cheap (single-threaded exhaustion test is the required minimum).
Full suite per commit.

## Report back
Per item: mechanism + verification. Item 1's factory surface chosen.
Item 2's shape chosen + the ~10-line user wiring demonstrated. Item
4's objdump evidence. Suite tally; deviations; non-allowlisted
commands.
