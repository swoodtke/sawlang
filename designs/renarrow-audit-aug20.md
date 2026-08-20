# Re-narrowing remainder audit (Aug 20, 2026)

Sweep-agent report (read-only; compile evidence throughout, no suite lock
taken). The DF-232f rider's remaining audit: every leftover `public` that
the Aug-20 kcore re-narrowing did not cover. The implementing unit applies
the site list below; the worktree that produced it was discarded after this
report was extracted.

## Verdict

86 candidates audited — **84 NARROWABLE, 2 CONSUMED** (`Console.write_str`,
`Console.write_hex`), 0 TEST-ONLY, 0 OPEN. 78 of the 84 could take `private`
outright (file-local); the six needing `public(package)` are listed under
"the package-tier six". Final narrowed state compiled green: kernel lane
53/53 (both arches), process lane 40/40 (both arches), blade + every
libs/blade test.

**CORRECTION (Aug 20, the implementing pass — DF-232q):** the
private-vs-package SPLIT above is INVERTED. The implementing agent's
iterated convergence found 72 of the "78 file-local" sites have kcore
SIBLING consumers (`process.saw`, `irq.saw`, `dispatch.saw`) hidden behind
three successive error waves — the one-pass census under-count this
report's own finding 3 (DF-232p) names, at a scale it did not anticipate.
The true split: **6 take `private`** (`Console.write_byte`, the two sosabi
statics, the two hal-arm64 funcs, `ReqKind`) and **78 take
`public(package)`**. The OUTER boundary — 84 narrowable vs 2 consumed,
zero reverts to `public` — held exactly. The tier column of the TSV below
is superseded by this correction; the site LIST itself remains exact.

## Count reconciliation — the rider's "~179" is exact, not approximate

Enumerated with sawc's own lexer+parser (never grep): kcore 80 public
members (65 fields + 15 ext methods), sysapi 30, imgformat 29, toml 26,
semver 8, sosabi 6, hal-arm64/hal-riscv32/sosrt 0 each — sum **179**. The
rider's number was the ALL-PACKAGES sum; kcore's own share is 80. kcore
top-level is 11 public + 7 `public import` re-exports, reproducing the
landed "119 -> 11".

NOT candidates, by the rider's own protection (API packages whose surface
is ruled, not usage-derived): sysapi's 30, imgformat's 29, toml's other 25,
semver's other 7, sosabi's other 4. Counted so the 179 ledger closes;
never to be acted on mechanically.

## The NARROWABLE 84 (file, line, kind, owner, symbol) — all `public` today

Proposed tier `public(package)`; 78 of them are file-local and `private`
would do (see below).

```tsv
sos/kernel/core/diag.saw	65	ext-method	Console	write_byte
sos/kernel/core/objects.saw	47	field	HandleEntry	obj_type
sos/kernel/core/objects.saw	48	field	HandleEntry	rights
sos/kernel/core/objects.saw	49	field	HandleEntry	target
sos/kernel/core/objects.saw	63	field	SystemObject	handle
sos/kernel/core/objects.saw	64	field	SystemObject	rights
sos/kernel/core/objects.saw	73	ext-method	SystemObject	allows
sos/kernel/core/objects.saw	81	field	ProcessObject	handle
sos/kernel/core/objects.saw	82	field	ProcessObject	rights
sos/kernel/core/objects.saw	83	field	ProcessObject	slot
sos/kernel/core/objects.saw	87	ext-method	ProcessObject	allows
sos/kernel/core/objects.saw	95	field	ThreadObject	handle
sos/kernel/core/objects.saw	96	field	ThreadObject	rights
sos/kernel/core/objects.saw	97	field	ThreadObject	slot
sos/kernel/core/objects.saw	101	ext-method	ThreadObject	allows
sos/kernel/core/objects.saw	109	field	EventObject	handle
sos/kernel/core/objects.saw	110	field	EventObject	rights
sos/kernel/core/objects.saw	111	field	EventObject	slot
sos/kernel/core/objects.saw	115	ext-method	EventObject	allows
sos/kernel/core/objects.saw	123	field	WaiterObject	handle
sos/kernel/core/objects.saw	124	field	WaiterObject	rights
sos/kernel/core/objects.saw	125	field	WaiterObject	slot
sos/kernel/core/objects.saw	129	ext-method	WaiterObject	allows
sos/kernel/core/objects.saw	137	field	InterruptObject	handle
sos/kernel/core/objects.saw	138	field	InterruptObject	rights
sos/kernel/core/objects.saw	139	field	InterruptObject	slot
sos/kernel/core/objects.saw	143	ext-method	InterruptObject	allows
sos/kernel/core/objects.saw	151	field	ClockObject	handle
sos/kernel/core/objects.saw	152	field	ClockObject	rights
sos/kernel/core/objects.saw	153	field	ClockObject	slot
sos/kernel/core/objects.saw	157	ext-method	ClockObject	allows
sos/kernel/core/objects.saw	165	field	TimerObject	handle
sos/kernel/core/objects.saw	166	field	TimerObject	rights
sos/kernel/core/objects.saw	167	field	TimerObject	slot
sos/kernel/core/objects.saw	171	ext-method	TimerObject	allows
sos/kernel/core/result.saw	26	field	SyscallResult	blocked
sos/kernel/core/threads.saw	90	field	ThreadSlot	state
sos/kernel/core/threads.saw	91	field	ThreadSlot	process
sos/kernel/core/threads.saw	94	field	ThreadSlot	self_handle
sos/kernel/core/threads.saw	95	field	ThreadSlot	exit_code
sos/kernel/core/threads.saw	97	field	ThreadSlot	joiners
sos/kernel/core/threads.saw	100	field	ThreadSlot	link
sos/kernel/core/threads.saw	106	field	ThreadSlot	wait_buf
sos/kernel/core/time.saw	41	field	ClockSlot	kind
sos/kernel/core/time.saw	70	field	TimerSlot	state
sos/kernel/core/time.saw	71	field	TimerSlot	process
sos/kernel/core/time.saw	73	field	TimerSlot	clock
sos/kernel/core/time.saw	75	field	TimerSlot	armed
sos/kernel/core/time.saw	77	field	TimerSlot	deadline_ns
sos/kernel/core/time.saw	79	field	TimerSlot	interval_ns
sos/kernel/core/time.saw	85	field	TimerSlot	fires
sos/kernel/core/time.saw	90	field	TimerSlot	attachment
sos/kernel/core/time.saw	190	ext-method	TimerSlot	arm
sos/kernel/core/time.saw	203	ext-method	TimerSlot	disarm
sos/kernel/core/time.saw	218	ext-method	TimerSlot	is_due
sos/kernel/core/time.saw	249	ext-method	TimerSlot	fire
sos/kernel/core/waitables.saw	51	field	Waitable	kind
sos/kernel/core/waitables.saw	52	field	Waitable	slot
sos/kernel/core/waitables.saw	77	field	EventSlot	state
sos/kernel/core/waitables.saw	78	field	EventSlot	process
sos/kernel/core/waitables.saw	80	field	EventSlot	mode
sos/kernel/core/waitables.saw	82	field	EventSlot	word
sos/kernel/core/waitables.saw	84	field	EventSlot	attachment
sos/kernel/core/waitables.saw	104	field	InterruptSlot	state
sos/kernel/core/waitables.saw	105	field	InterruptSlot	process
sos/kernel/core/waitables.saw	107	field	InterruptSlot	line
sos/kernel/core/waitables.saw	109	field	InterruptSlot	pending
sos/kernel/core/waitables.saw	111	field	InterruptSlot	attachment
sos/kernel/core/waitables.saw	123	field	WaiterSlot	state
sos/kernel/core/waitables.saw	124	field	WaiterSlot	process
sos/kernel/core/waitables.saw	126	field	WaiterSlot	attached
sos/kernel/core/waitables.saw	128	field	WaiterSlot	blocked
sos/kernel/core/waitables.saw	144	field	Attachment	state
sos/kernel/core/waitables.saw	146	field	Attachment	kind
sos/kernel/core/waitables.saw	148	field	Attachment	target
sos/kernel/core/waitables.saw	150	field	Attachment	waiter
sos/kernel/core/waitables.saw	153	field	Attachment	key
sos/kernel/core/waitables.saw	155	field	Attachment	link
sos/kernel/abi/src/lib.saw	1187	static	-	PROCESS_STATUS_KIND_SHIFT
sos/kernel/abi/src/lib.saw	1188	static	-	PROCESS_STATUS_CODE_MASK
sos/hal/arm64/kernel/lib.saw	793	func	-	mair_value
sos/hal/arm64/kernel/lib.saw	868	func	-	page_tables_build
libs/semver/src/lib.saw	94	enum	-	ReqKind
libs/toml/src/lib.saw	61	struct	-	TomlTable
```

### The package-tier six (everything else could be `private`)

Cross-file-in-package consumers, all from `sos/kernel/core/waitables.saw`:
`TimerSlot.fires`, `TimerSlot.attachment`, `ThreadSlot.state`,
`ThreadSlot.link`, `ThreadSlot.wait_buf`; plus `libs/toml/src/lib.saw`
`TomlTable` (toml's own tests fail at `private` — but see the oracle
caveat). Single-file packages (sosabi, hal-arm64, toml, semver): the
package tier buys nothing over `private` there — `private` is the honest
tier for five of those six.

## CONSUMED (2) — keep `public`; matches the facade's survivor set

- `Console.write_str` (diag.saw:72): 25 outside-kcore sites — kernel
  main.saw:25-27 and sos/tests/{extirq,threads_timer,timer_mask,timer,
  umode}.saw. Refusal text confirmed live.
- `Console.write_hex` (diag.saw:85): 4 sites — sos/tests/{trap:29,
  panic_from_check:51,timer_mask:47,extirq:36}.saw.
- `Console.write_byte` — third method of the same extension — has no
  outside consumer and narrows.

## Oracle caveat (a finding in its own right; filed as DF-232n)

**`public(package)` is NOT enforced across a relative-path import.**
`libs/toml/tests/*.saw` reach the package via `import src.lib.*` — no
`--module-path`, no mapped-package identity, so the empty-root fail-open
arm survives (`check_visibility`'s `if not package_root: return True`).
Probe: `TomlDoc` narrowed — blade REFUSED (`error: `TomlDoc` is
public(package) in `toml``) while all four toml tests compiled CLEAN
against the same source. Same for `semver.Version`. The toml/semver
verdicts therefore rest on the blade compile, a proven-live oracle.

## Other findings (reported for lead triage)

1. `public(package) extension Console` (diag.saw:63) does NOT clamp its
   `public` methods — the member tier gates, the extension tier is inert.
   Only such site in the tree. Ruling owed: gate or decoration?
2. A visibility-refused type re-resolves to a distinct same-named type,
   producing "expects `SosStatus` but got `SosStatus`" cascades (100+
   lines burying the one true refusal), and — reached through the
   design-141 place lowering — a `private` type surfaces as place/optional
   type errors with NO visibility error at all.
3. A refused call swallows a refusal in its own argument
   (`uart.write_str(hal.arch_name())` reports only `write_str`): an error
   census from one batch flip under-counts — the implementing agent must
   iterate to a clean build, never trust one pass.
4. No survey-counted symbol has vanished; no narrowable member lives in a
   conforming extension (the `format` conformances were never candidates)
   — nothing here changes behavior rather than visibility.

## Replayable build lanes

Python: `./.venv/bin/python`. Kernel lane: each of the 11 kernel/test
entries x {riscv32-unknown-none-elf +m,+a,+c | aarch64-unknown-none-elf}:
`sawc <SRC> -o <OBJ> --freestanding --no-hidden-alloc --runtime-provider
--target <TRIPLE> [--target-features <F>] --module-path
kcore=sos/kernel/core --module-path hal=sos/hal/<ARCH>/kernel
--module-path imgformat=sos/imgformat/src --module-path
sosrt=sos/rt/common/src --module-path sosabi=sos/kernel/abi/src`.
Process lane: sos/root + the 19 sos/tests root packages with
`--module-path sos=sos/kernel/sysapi/src` + sosabi + sosrt. Blade lane:
blade/src/main.saw with toml/semver/imgformat mappings. Package tests:
libs/{toml,semver}/tests/*.saw + blade/tests/*.saw with the same mappings.

Compile-cycle log: narrow-all -> 16 failures naming exactly 2 symbols ->
re-widen 2 -> green; a `private` probe isolated the package-tier six; two
controls proved every lane refuses when it should.
