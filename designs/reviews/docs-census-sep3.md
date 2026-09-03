# Design 262 U0 — Documentation Census (Sep 3 2026)

Read-only sweep of the four sources. No tracked file was modified. Every
probe lives under `/Users/shawn/Projects/sawlang/.build/scratch/docscensus/`;
every extraction/analysis script under `/Users/shawn/Projects/sawlang/.build/scratch/probe_*.py`.

**VERDICT: the docs' feature claims are in far better shape than the brief's
risk ranking assumed — the two highest-priority checks (the 234 `try_`
retirement and the 242 `Thread`/`Task` split) come back CLEAN in all four
sources, and the spec's error demos quote the compiler's real diagnostic text
almost verbatim. What is NOT in good shape is the block corpus's
*verifiability*: 348 of 440 Saw-tagged blocks (79%) are refused by every
spelling I tried, and the `saw-error` marker as specified in §1 of the brief
is VACUOUS for most of them — `sawc` fails a main-less file with ``no `main`
function found`` before it ever reaches the claimed check, so an
exit-code-only `saw-error` lane would pass ~300 blocks without testing
anything. Eleven C-findings, of which five are doc corrections with
compile/run evidence, four are harness-design facts U1 must absorb, and two
are brief-sizing corrections.**

---

## 0. Summary counts

### Fence counts (my extraction vs the brief's §0 numbers)

| Source | fence LINES | fence BLOCKS | `saw`-tagged | other tags | brief said |
|---|---|---|---|---|---|
| README.md (991 lines) | 64 | 32 | 23 | 7 bash, 1 toml, 1 bare | "64 fences / 23 tagged" ✅ |
| CLAUDE.md (542 lines) | 10 | 5 | 0 | 4 bash, 1 bare (repo map) | "no code blocks" ❌ — see **C10** |
| LANGUAGE_SPEC.md (11,918) | 742 | 371 | 330 | 1 bash, 1 text, 39 bare | "708 fences / 316 tagged" (drifted up) |
| .claude/skills/saw-lang/SKILL.md (3,987) | 176 | 88 | 87 | 1 bare | "30 fences / 15 tagged" ❌ — see **C11** |
| **TOTAL** | **992** | **496** | **440** | **56** | |

Also: `SUSPECT in older builds` callouts are **39 in the skill, 5 in the spec
(44)**, not the brief's 34/4/38.

### Probes run

| Attempt | What | Blocks tried | Accepted |
|---|---|---|---|
| A. as-is | `sawc <block>.saw -o <bin>` | 440 | 19 |
| B. `+main` | body + `func main() {}` appended | 421 | 52 |
| C. wrap-in-main | imports hoisted, rest wrapped in `func main { }` | 363 | 20 |
| D. `-c` | `sawc <block>.saw -c -o <obj>` (object only, no main required, no link) | 440 | 72 |
| **UNION** | accepted by **at least one** spelling | 440 | **92** |

**1,664 individual sawc invocations. No suite, battery or freestanding run
was started. Zero tracebacks and zero `internal compiler error` across all
1,664 — the fuzz oracle is clean on the whole doc corpus.**

### Classification (Saw-tagged blocks only)

| Source | complete-program | error-demo (confirmed) | error-demo (unconfirmed) | fragment (promotable) | fragment | fragment (elision) | non-Saw |
|---|---|---|---|---|---|---|---|
| README | 4 | 0 | 1 | 6 | 11 | 1 | 9 |
| CLAUDE | 0 | 0 | 0 | 0 | 0 | 0 | 5 |
| SPEC | 14 | 5 | 92 | 36 | 145 | 38 | 41 |
| SKILL | 1 | 3 | 14 | 8 | 48 | 13 | 1 |
| **TOTAL** | **19** | **8** | **107** | **50** | **204** | **52** | **56** |

"error-demo (confirmed)" = the compiler's refusal landed ON a line the doc
marked with an error comment. "unconfirmed" = the doc marks a refusal but the
compiler refused first for a different, scaffolding reason — see **C1**.

### Findings by column

| | count |
|---|---|
| MISSING | 2 (C6, C7) |
| WRONG (compile/run evidence) | 4 (C4, C5, C8, C9) |
| INCONSISTENT | 1 (C5, which is also a WRONG) |
| Harness-design facts for U1 | 4 (C1, C2, C3, plus the `-c` measurement) |
| Brief-sizing corrections | 2 (C10, C11) |

---

## Grid (a) — BLOCK INVENTORY

Columns: source:line-span | current tag | classification | proposed design-262
marker | evidence.

`WRAPPABLE` on a row means attempt C succeeded — the block's body is a valid
statement sequence and U2 can promote it by wrapping in `main` rather than
appending one.


### README.md — 32 blocks

| block | tag | class | marker | evidence |
|---|---|---|---|---|
| README:58-88 | `saw` | complete-program | `saw` | compiles as-is |
| README:100-120 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| README:130-155 | `saw` | complete-program (comment says 'error' but it is PROSE) | `saw` | compiles as-is |
| README:167-178 | `saw` | fragment | `saw-fragment` | error: undefined type 'ParseError' |
| README:187-193 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [2], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| README:203-212 | `saw` | fragment | `saw-fragment` | error: Parse error at 8:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| README:230-236 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| README:251-263 | `saw` | complete-program | `saw` | compiles as-is |
| README:273-287 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| README:292-297 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got MATCH |
| README:305-312 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| README:326-336 | `saw` | fragment | `saw-fragment` | error: cannot extend undefined struct 'Robot' |
| README:341-345 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| README:350-356 | `saw` | fragment | `saw-fragment` | error: Parse error at 3:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| README:361-364 | `saw` | fragment | `saw-fragment` | error: 'Version' cannot be conformed to 'Comparable' here: this module defines neither the type nor the trait |
| README:387-401 | `saw` | complete-program | `saw` | compiles as-is |
| README:410-416 | `saw` | fragment | `saw-fragment` | error: undefined function 'work' |
| README:433-442 | `saw` | fragment | `saw-fragment` | Linking failed: Undefined symbols for architecture arm64: — `-c` OK; **FLAG: declares func main yet does not compile** |
| README:458-466 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 1:41: Unexpected token: ELLIPSIS — **FLAG: declares func main yet does not compile** |
| README:494-504 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| README:524-532 | `saw` | fragment | `saw-fragment` | error: Parse error at 7:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| README:550-554 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| README:708-728 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| README:733-736 | `bash` | non-Saw | stay-bare | fence tag bash |
| README:764-767 | `bash` | non-Saw | stay-bare | fence tag bash |
| README:771-777 | `bash` | non-Saw | stay-bare | fence tag bash |
| README:784-787 | `bash` | non-Saw | stay-bare | fence tag bash |
| README:801-832 | `bash` | non-Saw | stay-bare | fence tag bash |
| README:839-849 | `bash` | non-Saw | stay-bare | fence tag bash |
| README:861-879 | `bash` | non-Saw | stay-bare | fence tag bash |
| README:885-890 | `toml` | non-Saw | stay-bare | fence tag toml |
| README:930-948 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |

### CLAUDE.md — 5 blocks

| block | tag | class | marker | evidence |
|---|---|---|---|---|
| CLAUDE:11-42 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| CLAUDE:52-55 | `bash` | non-Saw | stay-bare | fence tag bash |
| CLAUDE:60-68 | `bash` | non-Saw | stay-bare | fence tag bash |
| CLAUDE:126-129 | `bash` | non-Saw | stay-bare | fence tag bash |
| CLAUDE:157-163 | `bash` | non-Saw | stay-bare | fence tag bash |

### .claude/skills/saw-lang/SKILL.md — 88 blocks

| block | tag | class | marker | evidence |
|---|---|---|---|---|
| SKILL:14-50 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [16, 18, 30, 32], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SKILL:78-89 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got GUARD |
| SKILL:170-173 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SKILL:226-232 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3, 4], refused at []: error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SKILL:242-246 | `saw` | error-demo | `saw-error` | refuses AT the marked line [2]: error: no 'main' function found |
| SKILL:257-265 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [2, 6], refused at []: error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SKILL:306-313 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [2, 4], refused at []: error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SKILL:383-388 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 2:5: Unexpected token: ELLIPSIS |
| SKILL:427-431 | `saw` | fragment | `saw-fragment` | error: 'Holder' cannot be conformed to 'NoCopy' here: this module defines neither the type nor the trait |
| SKILL:440-443 | `saw` | fragment | `saw-fragment` | error: Parse error at 2:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SKILL:459-465 | `saw` | fragment | `saw-fragment` | error: undefined type 'Tape' |
| SKILL:500-503 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [1], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SKILL:508-514 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SKILL:524-529 | `saw` | fragment | `saw-fragment` | error: Parse error at 4:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SKILL:636-639 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 1:39: Unexpected token: ELLIPSIS |
| SKILL:664-670 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [1, 2, 3], refused at []: error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SKILL:692-701 | `saw` | fragment | `saw-fragment` | error: Parse error at 8:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SKILL:782-787 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got MATCH |
| SKILL:798-809 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:15: Expected function name |
| SKILL:851-859 | `saw` | fragment | `saw` — U2: wrap body in `main` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET — WRAPPABLE |
| SKILL:933-945 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got MATCH |
| SKILL:991-998 | `saw` | error-demo | `saw-error` | refuses AT the marked line [3]: error: 'Slot' is not in the prelude and must be imported |
| SKILL:1015-1038 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [8, 17], refused at []: error: Parse error at 2:32: Unexpected token: ELLIPSIS |
| SKILL:1042-1051 | `saw` | fragment | `saw-fragment` | error: undefined type 'ParseError' |
| SKILL:1072-1074 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SKILL:1094-1101 | `saw` | fragment | `saw-fragment` | error: 'IoError' is not in the prelude and must be imported — **FLAG: declares func main yet does not compile** |
| SKILL:1129-1139 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 8:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SKILL:1181-1193 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SKILL:1218-1225 | `saw` | fragment | `saw-fragment` | error: undefined type 'Slotted' |
| SKILL:1309-1314 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SKILL:1353-1356 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SKILL:1416-1426 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SKILL:1433-1443 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 3:53: Unexpected token: ELLIPSIS |
| SKILL:1528-1533 | `saw` | fragment | `saw-fragment` | error: 'Point' cannot be conformed to 'Equatable' here: this module defines neither the type nor the trait |
| SKILL:1564-1570 | `saw` | fragment | `saw-fragment` | error: Parse error at 4:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SKILL:1595-1603 | `saw` | fragment | `saw-fragment` | error: Parse error at 6:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got TRY |
| SKILL:1631-1638 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SKILL:1666-1671 | `saw` | error-demo | `saw-error` | refuses AT the marked line [3]: error: no 'main' function found |
| SKILL:1681-1690 | `saw` | fragment | `saw-fragment` | error: Parse error at 8:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SKILL:1702-1705 | `saw` | fragment | `saw-fragment` | error: Parse error at 2:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SKILL:1711-1717 | `saw` | fragment | `saw` — U2: wrap body in `main` | error: Parse error at 2:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR — WRAPPABLE |
| SKILL:1727-1743 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 9:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT — **FLAG: declares func main yet does not compile** |
| SKILL:1750-1757 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SKILL:1852-1856 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SKILL:1879-1884 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [1, 3], refused at []: error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SKILL:1907-1912 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SKILL:1923-1926 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SKILL:1946-1950 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [2], refused at []: error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SKILL:1989-1995 | `saw` | fragment | `saw-fragment` | error: 'Channel' is not in the prelude and must be imported |
| SKILL:2005-2021 | `saw` | fragment | `saw-fragment` | error: 'Channel' is not in the prelude and must be imported |
| SKILL:2046-2055 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SKILL:2086-2092 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got MATCH |
| SKILL:2136-2148 | `saw` | fragment | `saw-fragment` | error: cannot extend undefined struct 'Store' — **FLAG: declares func main yet does not compile** |
| SKILL:2176-2181 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got WHILE |
| SKILL:2191-2199 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got TRY |
| SKILL:2209-2214 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IF |
| SKILL:2239-2249 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SKILL:2294-2302 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SKILL:2343-2347 | `saw` | fragment | `saw-fragment` | error: cannot extend undefined struct 'Color' |
| SKILL:2425-2429 | `saw` | fragment-elision | `saw-fragment` | error: Lexer error at 3:26: Unexpected character: … |
| SKILL:2481-2492 | `saw` | fragment | `saw-fragment` | error: 'TcpStream' is not in the prelude and must be imported |
| SKILL:2506-2511 | `saw` | fragment | `saw-fragment` | error: 'Mutex' is not in the prelude and must be imported |
| SKILL:2538-2545 | `saw` | fragment-elision | `saw-fragment` | error: Lexer error at 1:51: Unexpected character: … |
| SKILL:2566-2575 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [4], refused at []: error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SKILL:2618-2624 | `saw` | fragment | `saw-fragment` | error: module 'mymodule' not found |
| SKILL:2664-2669 | `saw` | fragment | `saw-fragment` | error: 'Path' is not in the prelude and must be imported |
| SKILL:2688-2695 | `saw` | complete-program (comment says 'error' but it is PROSE) | `saw` | compiles as-is |
| SKILL:2941-2948 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3], refused at [1, 2]: error: function 'give' is public, but the return type names 'Hidden', which is private — a public API needs public types |
| SKILL:2990-2995 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got MATCH |
| SKILL:3018-3020 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SKILL:3089-3093 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SKILL:3107-3122 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SKILL:3193-3197 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SKILL:3212-3218 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SKILL:3329-3336 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 1:31: Expected field name |
| SKILL:3417-3421 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 2:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SKILL:3437-3443 | `saw` | fragment | `saw-fragment` | error: Parse error at 5:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SKILL:3475-3482 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 4:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SKILL:3490-3499 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [6], refused at []: error: Parse error at 5:7: method 'dup' has no receiver — add '&self'/'&var self', or declare it 'static func' if a static was intended |
| SKILL:3549-3558 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SKILL:3629-3634 | `saw` | fragment | `saw-fragment` | error: cannot extend undefined struct 'Counter' |
| SKILL:3639-3645 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [2, 5], refused at [1, 4]: error: no 'main' function found |
| SKILL:3734-3737 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SKILL:3782-3791 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [7], refused at []: error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SKILL:3836-3841 | `saw` | fragment | `saw` — U2: wrap body in `main` | error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT — WRAPPABLE |
| SKILL:3877-3882 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SKILL:3907-3912 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SKILL:3943-3951 | `saw` | fragment | `saw-fragment` | error: Parse error at 6:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |

### LANGUAGE_SPEC.md — 371 blocks

| block | tag | class | marker | evidence |
|---|---|---|---|---|
| SPEC:62-82 | `saw` | complete-program | `saw` | compiles as-is |
| SPEC:88-92 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [2], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:98-106 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:112-117 | `saw` | fragment | `saw-fragment` | error: module 'kcore' not found |
| SPEC:123-126 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:136-148 | `saw` | fragment | `saw` — U2: wrap body in `main` | error: Parse error at 2:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET — WRAPPABLE |
| SPEC:165-168 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:177-189 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [10], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:221-252 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [18], refused at []: error: Parse error at 24:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SPEC:262-270 | `saw` | fragment | `saw-fragment` | error: Parse error at 6:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:291-299 | `saw` | fragment | `saw-fragment` | error: Parse error at 5:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SPEC:343-346 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:375-380 | `saw` | fragment | `saw-fragment` | error: Parse error at 2:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SPEC:406-411 | `saw` | fragment-elision | `saw-fragment` | error: Lexer error at 1:70: Unexpected character: … |
| SPEC:420-426 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [5], refused at []: error: Lexer error at 1:33: Unexpected character: … |
| SPEC:450-454 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [2], refused at [1]: error: 'main' must return 'Void', 'Int', 'Result<Void, E>' or 'Result<Int, E>', but returns 'String' |
| SPEC:461-473 | `saw` | complete-program | `saw` | compiles as-is |
| SPEC:521-533 | `saw` | complete-program | `saw` | compiles as-is |
| SPEC:537-623 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [34, 43], refused at []: error: Parse error at 2:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:634-647 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:670-675 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3], refused at [1]: error: no 'main' function found |
| SPEC:683-689 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:713-717 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [2], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:722-726 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got WHILE |
| SPEC:764-787 | `saw` | fragment | `saw-fragment` | error: Parse error at 2:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SPEC:891-901 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [8], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:924-933 | `saw` | fragment | `saw-fragment` | error: Parse error at 6:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SPEC:940-967 | `saw` | fragment | `saw-fragment` | error: undefined type 'Entry' |
| SPEC:987-994 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:1131-1139 | `saw` | fragment | `saw` — U2: wrap body in `main` | error: Parse error at 3:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR — WRAPPABLE |
| SPEC:1210-1212 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:1245-1253 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:1257-1264 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [5], refused at []: error: Parse error at 1:1: doc comment is not followed by a documentable declaration |
| SPEC:1280-1418 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [28, 29, 39, 87, 90, 98, 105], refused at []: error: Parse error at 2:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:1442-1448 | `saw` | fragment | `saw-fragment` | error: 'self' can only be used inside methods |
| SPEC:1460-1463 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:1473-1505 | `saw` | fragment | `saw-fragment` | error: Parse error at 27:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:1520-1553 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [25], refused at []: error: Parse error at 20:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:1574-1583 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [4], refused at [1, 2, 3, 6]: error: 'Slot' is not in the prelude and must be imported |
| SPEC:1589-1602 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [12], refused at []: error: Parse error at 7:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:1609-1620 | `saw` | fragment | `saw-fragment` | error: Parse error at 7:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:1627-1651 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:1656-1673 | `saw` | fragment | `saw-fragment` | error: 'SysError' cannot be conformed to 'Printable' here: this module defines neither the type nor the trait |
| SPEC:1684-1690 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [4], refused at [1, 2]: error: cannot extend undefined struct 'Color' |
| SPEC:1700-1710 | `saw` | fragment | `saw-fragment` | error: Parse error at 7:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:1732-1737 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:1741-1747 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IF |
| SPEC:1768-1784 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:1795-1814 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:1831-1836 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:1841-1852 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:1856-1866 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [5], refused at [1]: error: recursive type 'Tree' has infinite size: its storage contains its own storage inline, through Tree.Node.child -> Tree |
| SPEC:1879-1920 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 4:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:1950-1957 | `saw` | fragment | `saw-fragment` | error: undefined type 'Slotted' |
| SPEC:2014-2017 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SPEC:2057-2062 | `saw` | fragment | `saw` — U2: wrap body in `main` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR — WRAPPABLE |
| SPEC:2067-2076 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [5], refused at []: error: Parse error at 3:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:2091-2100 | `saw` | fragment | `saw-fragment` | error: 'File' is not in the prelude and must be imported |
| SPEC:2115-2122 | `saw` | fragment | `saw-fragment` | error: 'File' is not in the prelude and must be imported |
| SPEC:2144-2151 | `saw` | fragment-elision | `saw-fragment` | error: Lexer error at 1:43: Unexpected character: … |
| SPEC:2179-2224 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 32:49: Unexpected token: ELLIPSIS |
| SPEC:2233-2243 | `saw` | fragment | `saw-fragment` | error: cannot extend undefined struct 'Point' |
| SPEC:2278-2306 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:2337-2348 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got MATCH |
| SPEC:2370-2380 | `saw` | fragment | `saw-fragment` | error: trait 'Printable' is defined multiple times |
| SPEC:2396-2421 | `saw` | fragment | `saw-fragment` | error: Parse error at 23:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:2428-2433 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SPEC:2439-2442 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [2], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SPEC:2457-2460 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SPEC:2487-2495 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:2506-2519 | `saw` | fragment | `saw-fragment` | error: 'Point' cannot be conformed to 'Printable' here: this module defines neither the type nor the trait |
| SPEC:2538-2544 | `saw` | fragment | `saw` — U2: wrap body in `main` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR — WRAPPABLE |
| SPEC:2550-2552 | `saw` | fragment | `saw-fragment` | error: trait 'Error' is defined multiple times |
| SPEC:2573-2586 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:2606-2611 | `saw` | error-demo | `saw-error` | refuses AT the marked line [3]: error: type alias 'Rank' names the enum 'Level', and an alias of an enum is not allowed |
| SPEC:2617-2632 | `saw` | fragment | `saw-fragment` | error: Parse error at 6:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:2649-2655 | `saw` | fragment | `saw-fragment` | error: Parse error at 4:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:2668-2680 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3, 4], refused at []: error: Parse error at 6:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:2696-2747 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 29:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:2754-2761 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:2767-2774 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 4:50: Unexpected token: ELLIPSIS |
| SPEC:2791-2809 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:2818-2826 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [4, 7], refused at []: error: Parse error at 2:36: Unexpected token: ELLIPSIS |
| SPEC:2854-2865 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [8], refused at []: error: Parse error at 7:5: method 'dup' has no receiver — add '&self'/'&var self', or declare it 'static func' if a static was intended |
| SPEC:2906-2913 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3], refused at [1, 2]: error: cannot extend undefined struct 'Counter' |
| SPEC:2929-2936 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3], refused at [1, 2]: error: cannot extend undefined struct 'Bag' |
| SPEC:2945-2956 | `saw` | error-demo | `saw-error` | refuses AT the marked line [8]: error: undefined type 'Grid' |
| SPEC:3065-3069 | `saw` | fragment | `saw-fragment` | error: 'Res' cannot be conformed to 'NoCopy' here: this module defines neither the type nor the trait |
| SPEC:3077-3086 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [6], refused at [1, 2, 5]: error: 'Ticket' cannot be conformed to 'Copy' here: this module defines neither the type nor the trait |
| SPEC:3098-3103 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:3111-3124 | `saw` | fragment | `saw` — U2: wrap body in `main` | error: Parse error at 2:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET — WRAPPABLE |
| SPEC:3134-3138 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:3158-3166 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:3179-3188 | `saw` | complete-program | `saw` | compiles as-is |
| SPEC:3196-3199 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:3204-3215 | `saw` | error-demo | `saw-error` | refuses AT the marked line [7]: error: cannot copy value of type 'Ticket' which implements NoCopy |
| SPEC:3239-3246 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [4], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:3264-3270 | `saw` | fragment | `saw` — U2: wrap body in `main` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR — WRAPPABLE |
| SPEC:3278-3293 | `saw` | fragment | `saw-fragment` | error: undefined type 'Tape' |
| SPEC:3315-3331 | `saw` | fragment | `saw-fragment` | error: Parse error at 13:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:3341-3353 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [11], refused at []: error: Parse error at 9:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:3370-3375 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:3408-3417 | `saw` | fragment | `saw-fragment` | error: 'Data' is not in the prelude and must be imported |
| SPEC:3435-3441 | `saw` | fragment | `saw-fragment` | error: cannot extend undefined struct 'Pair' |
| SPEC:3471-3503 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 6:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:3550-3559 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3], refused at []: error: Parse error at 2:25: method 'peek' may not return a reference: the return type '&Int' is a reference, and references in Saw are PARAMETERS ONLY — a refer |
| SPEC:3629-3638 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [7], refused at []: error: Parse error at 7:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:3640-3649 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [2, 7], refused at []: error: Parse error at 1:20: field 'r' of 'Holder' may not be a reference: its type '&Int' is a reference, and references in Saw are PARAMETERS ONLY — a referenc |
| SPEC:3658-3666 | `saw` | fragment | `saw-fragment` | error: cannot extend undefined struct 'Counter' |
| SPEC:3675-3685 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3, 9], refused at [2, 8]: error: an escaping closure cannot capture 'r', a reference ('&Thing') — a reference borrows storage for the duration of one call and may not outlive the frame i |
| SPEC:3699-3704 | `saw` | fragment | `saw-fragment` | error: cannot extend undefined struct 'Counter' |
| SPEC:3711-3717 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3], refused at [1, 2]: error: cannot extend undefined struct 'Counter' |
| SPEC:3739-3747 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [6, 7], refused at []: error: Parse error at 4:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:3759-3775 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [8], refused at [1, 10]: error: cannot extend undefined struct 'Counter' |
| SPEC:3791-3796 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 2:38: Unexpected token: ELLIPSIS |
| SPEC:3806-3819 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [5, 9], refused at []: error: Parse error at 1:39: Unexpected token: ELLIPSIS |
| SPEC:3852-3861 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:3869-3871 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [1], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SPEC:3875-3878 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:3885-3892 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [2], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:3906-3911 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:3930-3945 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 12:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:3964-3974 | `saw` | fragment | `saw-fragment` | error: cannot extend undefined struct 'Ledger' |
| SPEC:3994-4001 | `saw` | error-demo | `saw-error` | refuses AT the marked line [4]: error: 'lend tmp' is not rooted in the receiver: 'tmp' is this accessor's own local or parameter, so the window would open onto storage that dies when the acces |
| SPEC:4030-4034 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SPEC:4041-4046 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SPEC:4087-4102 | `saw` | fragment | `saw-fragment` | error: field 'length' of struct 'Data' is private and not accessible from this module |
| SPEC:4123-4128 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:4173-4180 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:4187-4190 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [2], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:4197-4200 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SPEC:4212-4221 | `saw` | fragment | `saw-fragment` | error: cannot extend undefined struct 'Grid' |
| SPEC:4232-4236 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SPEC:4280-4286 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IF |
| SPEC:4298-4304 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 4:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:4319-4328 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [5], refused at []: error: Parse error at 6:9: Unexpected token: ELLIPSIS |
| SPEC:4342-4356 | `saw` | fragment | `saw-fragment` | error: undefined type 'Res' |
| SPEC:4368-4374 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:4395-4400 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [2], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SPEC:4431-4441 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:4457-4461 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IF |
| SPEC:4466-4474 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:4507-4520 | `saw` | fragment | `saw-fragment` | error: Parse error at 4:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:4527-4534 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [5], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:4546-4557 | `saw` | fragment | `saw-fragment` | error: Parse error at 2:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:4568-4576 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:4613-4618 | `saw` | fragment | `saw-fragment` | error: trait 'Deinit' is defined multiple times |
| SPEC:4646-4650 | `saw` | fragment | `saw-fragment` | error: trait 'Copy' is defined multiple times |
| SPEC:4658-4691 | `saw` | complete-program | `saw` | compiles as-is |
| SPEC:4701-4706 | `saw` | fragment | `saw-fragment` | error: trait 'ExplicitCopy' is defined multiple times |
| SPEC:4717-4728 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 2:31: Unexpected token: ELLIPSIS |
| SPEC:4732-4737 | `saw` | fragment | `saw-fragment` | error: trait 'NoCopy' is defined multiple times |
| SPEC:4741-4757 | `saw` | fragment | `saw-fragment` | error: Parse error at 11:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:4766-4769 | `saw` | fragment | `saw-fragment` | error: 'TaskGroup' cannot be conformed to 'NoCopy' here: this module defines neither the type nor the trait |
| SPEC:4780-4788 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [5], refused at [1, 3, 4]: error: no 'main' function found |
| SPEC:4795-4799 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:4808-4817 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 3:9: Unexpected token: ELLIPSIS |
| SPEC:4828-4836 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [5], refused at []: error: Parse error at 2:5: Unexpected token: ELLIPSIS |
| SPEC:4847-4852 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3], refused at [1]: error: 'Server' contains NoMove member 'group' of type 'TaskGroup' but does not declare 'NoMove': a value that cannot be relocated cannot be relocated inside so |
| SPEC:4884-4895 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [5], refused at [1, 2, 3]: error: 'File' is not in the prelude and must be imported |
| SPEC:4926-4934 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:4940-4947 | `saw` | fragment | `saw-fragment` | error: 'Connection' cannot be conformed to 'NoCopy' here: this module defines neither the type nor the trait |
| SPEC:4954-4960 | `saw` | fragment | `saw-fragment` | error: 'Container' cannot be conformed to 'Copy' here: this module defines neither the type nor the trait |
| SPEC:4976-4997 | `saw` | fragment-elision | `saw-fragment` | error: enum 'Result' is defined multiple times |
| SPEC:5010-5022 | `saw` | fragment-elision | `saw-fragment` | error: undefined type 'ParseError' |
| SPEC:5035-5042 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [5], refused at [1]: error: no 'main' function found — `-c` OK |
| SPEC:5053-5058 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 1:65: Unexpected token: ELLIPSIS |
| SPEC:5067-5072 | `saw` | fragment-elision | `saw-fragment` | error: undefined type 'Stop' |
| SPEC:5095-5101 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:5130-5133 | `saw` | fragment | `saw-fragment` | error: Parse error at 2:1: Expected LBRACE, got FUNC |
| SPEC:5145-5154 | `saw` | fragment | `saw-fragment` | error: 'Channel' is not in the prelude and must be imported |
| SPEC:5160-5172 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [1], refused at []: error: Parse error at 8:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:5179-5198 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 9:61: Unexpected token: ELLIPSIS |
| SPEC:5215-5219 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [2, 3], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:5232-5247 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [1, 4], refused at []: error: Parse error at 2:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:5261-5269 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got TRY |
| SPEC:5277-5297 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [13], refused at []: error: Parse error at 4:59: Unexpected token: ELLIPSIS |
| SPEC:5321-5334 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got TRY |
| SPEC:5352-5357 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got MATCH |
| SPEC:5365-5375 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [5], refused at [1, 4]: error: no 'main' function found |
| SPEC:5380-5384 | `saw` | fragment | `saw-fragment` | error: 'TcpStream' is not in the prelude and must be imported |
| SPEC:5389-5393 | `saw` | fragment | `saw-fragment` | error: 'TcpStream' is not in the prelude and must be imported |
| SPEC:5421-5428 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:25: Expected ';' in array type |
| SPEC:5442-5445 | `saw` | fragment | `saw` — U2: wrap body in `main` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT — WRAPPABLE |
| SPEC:5499-5505 | `saw` | fragment | `saw` — U2: wrap body in `main` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET — WRAPPABLE |
| SPEC:5549-5555 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:5589-5598 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [4], refused at [1, 2]: error: no 'main' function found |
| SPEC:5611-5618 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:5645-5650 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:5658-5664 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [4], refused at [1, 2]: error: no 'main' function found |
| SPEC:5681-5687 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:5747-5757 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:5773-5779 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [5], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:5793-5802 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [5], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:5824-5833 | `saw` | complete-program | `saw` | compiles as-is |
| SPEC:5873-5876 | `saw` | fragment | `saw-fragment` | error: 'Named' cannot be conformed to 'Equatable' here: this module defines neither the type nor the trait |
| SPEC:5903-5909 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:5952-5974 | `saw` | fragment | `saw-fragment` | error: Parse error at 16:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:5982-5991 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [4], refused at [1, 2]: error: 'Tag' cannot be conformed to 'Equatable' here: this module defines neither the type nor the trait |
| SPEC:6005-6009 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IF |
| SPEC:6029-6040 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:6063-6071 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:6100-6105 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:6131-6140 | `saw` | fragment | `saw-fragment` | error: Parse error at 3:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:6189-6196 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:6378-6381 | `text` | non-Saw | stay-bare | fence tag text |
| SPEC:6389-6392 | `saw` | fragment | `saw` — U2: wrap body in `main` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET — WRAPPABLE |
| SPEC:6411-6416 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:6519-6522 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:6531-6537 | `saw` | error-demo | `saw-error` | refuses AT the marked line [3]: error: no 'main' function found |
| SPEC:6558-6568 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:6779-6793 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [9], refused at [1, 3, 4]: error: cannot extend undefined struct 'Person' |
| SPEC:6866-6869 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:6889-6897 | `saw` | fragment | `saw-fragment` | error: 'Channel' is not in the prelude and must be imported |
| SPEC:6935-6952 | `saw` | fragment | `saw-fragment` | error: 'TcpStream' is not in the prelude and must be imported |
| SPEC:7179-7189 | `saw` | fragment | `saw-fragment` | error: Parse error at 2:3: Expected LBRACE, got PUBLIC |
| SPEC:7208-7223 | `saw` | fragment | `saw-fragment` | error: 'Channel' is not in the prelude and must be imported |
| SPEC:7238-7244 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:7362-7380 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [6], refused at []: error: Parse error at 2:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:7389-7399 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [2, 7], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SPEC:7410-7433 | `saw` | fragment | `saw-fragment` | error: undefined function 'serve' |
| SPEC:7443-7447 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:7459-7465 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:7483-7489 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 1:35: Unexpected token: ELLIPSIS |
| SPEC:7506-7516 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:7528-7532 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [2], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:7545-7551 | `saw` | fragment | `saw-fragment` | error: Parse error at 4:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:7555-7663 | `saw` | fragment-elision | `saw-fragment` | error: 'TcpStream' is not in the prelude and must be imported — **FLAG: declares func main yet does not compile** |
| SPEC:7671-7683 | `saw` | complete-program | `saw` | compiles as-is |
| SPEC:7700-7716 | `saw` | fragment | `saw-fragment` | error: undefined function 'open' — **FLAG: declares func main yet does not compile** |
| SPEC:7727-7732 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:7745-7749 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:7763-7772 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [5], refused at [1, 3, 4]: error: no 'main' function found |
| SPEC:7786-7789 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:7795-7801 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:7807-7817 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [4, 8], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:7825-7830 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:7847-7856 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [5], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:7868-7884 | `saw` | fragment | `saw-fragment` | error: Parse error at 11:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:7897-7904 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [5], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:7931-7936 | `saw` | fragment | `saw-fragment` | error: 'TcpStream' is not in the prelude and must be imported |
| SPEC:7938-7946 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:7974-7979 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:8034-8051 | `saw` | fragment-elision | `saw-fragment` | error: 'TcpStream' is not in the prelude and must be imported — **FLAG: declares func main yet does not compile** |
| SPEC:8076-8082 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got MATCH |
| SPEC:8112-8122 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:8150-8156 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [4], refused at [1, 2]: error: 'extern blocking func slow_named': parameter 's' has type 'String', which is not C-ABI-safe |
| SPEC:8167-8172 | `saw` | fragment | `saw-fragment` | error: undefined function 'read' |
| SPEC:8263-8266 | `saw` | fragment | `saw-fragment` | error: trait 'UnsafeSync' is defined multiple times |
| SPEC:8273-8276 | `saw` | fragment | `saw-fragment` | error: 'Mutex' cannot be conformed to 'UnsafeSync' here: this module defines neither the type nor the trait |
| SPEC:8316-8356 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:8366-8368 | `saw` | fragment | `saw-fragment` | error: 'SampleBuffer' cannot be conformed to 'UnsafeSend' here: this module defines neither the type nor the trait |
| SPEC:8391-8407 | `saw` | fragment | `saw-fragment` | error: undefined type 'SampleBuffer' — **FLAG: declares func main yet does not compile** |
| SPEC:8412-8418 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:8434-8480 | `saw` | complete-program | `saw` | compiles as-is |
| SPEC:8490-8499 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:8509-8511 | `saw` | fragment | `saw-fragment` | error: 'Mutex' cannot be conformed to 'UnsafeSync' here: this module defines neither the type nor the trait |
| SPEC:8516-8522 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3], refused at [1, 2]: error: 'Mutex' is not in the prelude and must be imported |
| SPEC:8538-8566 | `saw` | fragment | `saw-fragment` | error: undefined function 'SampleBuffer' — **FLAG: declares func main yet does not compile** |
| SPEC:8576-8594 | `saw` | fragment | `saw-fragment` | error: undefined function 'SampleBuffer' — **FLAG: declares func main yet does not compile** |
| SPEC:8605-8612 | `saw` | fragment | `saw-fragment` | error: undefined type 'Point' |
| SPEC:8689-8703 | `saw` | complete-program | `saw` | compiles as-is |
| SPEC:8710-8717 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3], refused at [1]: error: static 'LATER' is declared after this point |
| SPEC:8725-8730 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3, 4], refused at [1]: error: no 'main' function found |
| SPEC:8740-8746 | `saw` | fragment | `saw-fragment` | error: module 'dep' not found |
| SPEC:8762-8780 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:8824-8827 | `saw` | fragment | `saw-fragment` | error: Parse error at 2:1: Expected LBRACE, got FUNC |
| SPEC:8865-8885 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:8908-8917 | `saw` | complete-program | `saw` | compiles as-is |
| SPEC:8930-8934 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:8942-8951 | `saw` | complete-program | `saw` | compiles as-is |
| SPEC:8956-8962 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [2], refused at [1]: error: no 'main' function found — `-c` OK |
| SPEC:8975-8990 | `saw` | fragment | `saw-fragment` | error: Parse error at 13:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:9028-9042 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:9097-9112 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:9118-9135 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 5:71: Unexpected token: ELLIPSIS |
| SPEC:9176-9182 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 1:52: Expected field name |
| SPEC:9202-9221 | `saw` | fragment | `saw-fragment` | error: Parse error at 15:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:9253-9256 | `saw` | fragment | `saw-fragment` | error: Parse error at 2:3: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SPEC:9269-9279 | `saw` | fragment | `saw-fragment` | error: Parse error at 3:1: Expected LBRACE, got IDENT |
| SPEC:9286-9290 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [2], refused at [1]: error: 'Int' is a type, not a trait, so it cannot bound the type parameter 'N' |
| SPEC:9308-9318 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [8], refused at []: error: Parse error at 7:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SPEC:9336-9338 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:9415-9432 | `saw` | fragment | `saw-fragment` | error: undefined type 'UartRegs' |
| SPEC:9439-9446 | `saw` | fragment | `saw-fragment` | error: Parse error at 2:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SPEC:9450-9478 | `saw` | fragment-elision | `saw-fragment` | error: Lexer error at 2:15: Expected number after '$' for shorthand closure parameter |
| SPEC:9482-9494 | `saw` | fragment | `saw-fragment` | error: Parse error at 2:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SPEC:9509-9519 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 8:29: Unexpected token: ELLIPSIS |
| SPEC:9523-9533 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 2:19: Expected field name |
| SPEC:9546-9551 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:9560-9571 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 9:30: Unexpected token: ELLIPSIS |
| SPEC:9579-9584 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:9619-9627 | `saw` | fragment | `saw-fragment` | error: function 'give' is public, but the return type names 'Hidden', which is private — a public API needs public types |
| SPEC:9629-9636 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:9657-9667 | `saw` | fragment | `saw-fragment` | error: undefined type 'Hidden' |
| SPEC:9717-9724 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 4:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:9741-9744 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:9748-9752 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:9772-9787 | `saw` | fragment | `saw-fragment` | error: 'Reading' cannot be conformed to 'Printable' here: this module defines neither the type nor the trait |
| SPEC:9798-9809 | `saw` | fragment | `saw-fragment` | error: struct 'Header' is defined multiple times |
| SPEC:9820-9826 | `saw` | fragment | `saw-fragment` | error: Parse error at 4:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:9831-9839 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [5], refused at []: error: Parse error at 4:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:9851-9860 | `saw` | complete-program | `saw` | compiles as-is |
| SPEC:9899-9902 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [2], refused at [1]: error: 'Data' is not in the prelude and must be imported |
| SPEC:9921-9925 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [2], refused at [1]: error: 'OpenMode' is not defined in 'std.file' |
| SPEC:9946-9952 | `saw` | fragment | `saw-fragment` | error: 'Path' is not in the prelude and must be imported |
| SPEC:9967-9979 | `saw` | complete-program | `saw` | compiles as-is |
| SPEC:9990-9999 | `saw` | fragment | `saw-fragment` | error: module 'shapes' not found |
| SPEC:10004-10007 | `saw` | fragment | `saw` — U2: wrap body in `main` | error: Parse error at 2:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET — WRAPPABLE |
| SPEC:10011-10016 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3], refused at []: error: Parse error at 2:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:10024-10027 | `saw` | fragment | `saw-fragment` | error: module 'mypkg.collections' not found |
| SPEC:10032-10035 | `saw` | fragment | `saw-fragment` | error: module 'parser' not found |
| SPEC:10040-10045 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:10051-10055 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:10064-10069 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 4:45: Unexpected token: ELLIPSIS |
| SPEC:10071-10076 | `saw` | fragment | `saw-fragment` | error: module 'parser' not found |
| SPEC:10078-10083 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:10132-10138 | `saw` | fragment-elision | `saw-fragment` | error: module 'mine' not found |
| SPEC:10147-10152 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:10159-10170 | `saw` | complete-program | `saw` | compiles as-is |
| SPEC:10179-10185 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:10195-10200 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [2], refused at []: error: module 'data' not found |
| SPEC:10217-10223 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:10248-10272 | `saw` | fragment | `saw-fragment` | error: module 'panel' not found — **FLAG: declares func main yet does not compile** |
| SPEC:10295-10304 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:10311-10326 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:10423-10430 | `saw` | fragment | `saw` — U2: wrap body in `main` | error: Parse error at 3:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR — WRAPPABLE |
| SPEC:10437-10441 | `saw` | fragment | `saw` — U2: wrap body in `main` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET — WRAPPABLE |
| SPEC:10448-10452 | `saw` | fragment | `saw` — U2: wrap body in `main` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET — WRAPPABLE |
| SPEC:10476-10483 | `saw` | fragment | `saw` — U2: wrap body in `main` | error: Parse error at 3:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR — WRAPPABLE |
| SPEC:10571-10574 | `bash` | non-Saw | stay-bare | fence tag bash |
| SPEC:10603-10633 | `saw` | fragment-elision | `saw-fragment` | error: '@section(".text.boot")' is not a valid section on this target: mach-O names a section by SEGMENT and section, separated by a comma |
| SPEC:10639-10643 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:10648-10657 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [4], refused at [1]: error: no 'main' function found |
| SPEC:10671-10680 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [4, 8], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SPEC:10692-10695 | `saw` | fragment | `saw` — U2: wrap body in `main` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET — WRAPPABLE |
| SPEC:10701-10707 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3], refused at [1, 2]: error: no 'main' function found |
| SPEC:10714-10718 | `saw` | fragment | `saw-fragment` | error: Parse error at 3:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:10730-10737 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:10743-10748 | `saw` | fragment | `saw-fragment` | error: Parse error at 3:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:10756-10760 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:10765-10771 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:10845-10852 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3], refused at [1]: error: no 'main' function found |
| SPEC:10854-10859 | `saw` | fragment | `saw-fragment` | error: '@section(".vector_table")' is not a valid section on this target: mach-O names a section by SEGMENT and section, separated by a comma |
| SPEC:10866-10875 | `saw` | fragment-PROMOTABLE | `saw` — U2: append `func main() {}` | compiles once an empty main is appended — `-c` OK |
| SPEC:10929-10935 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3], refused at [1, 2]: error: an unsafe type must be named 'Unsafe*', but this one is named 'MmioReg' |
| SPEC:10973-10981 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:10992-11000 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [5], refused at [1, 3, 4]: error: cannot extend undefined struct 'Plain' |
| SPEC:11012-11016 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 1:48: Unexpected token: ELLIPSIS |
| SPEC:11021-11023 | `saw` | fragment | `saw-fragment` | error: Parse error at 4:1: Expected LBRACE, got FUNC |
| SPEC:11033-11036 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:11048-11058 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [3, 6], refused at []: error: Parse error at 2:1: Expected LBRACE, got FUNC |
| SPEC:11078-11086 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 5:9: Unexpected token: ELLIPSIS |
| SPEC:11096-11100 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:11113-11115 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got IDENT |
| SPEC:11124-11127 | `saw` | fragment | `saw-fragment` | error: Parse error at 2:1: Expected LBRACE, got IDENT |
| SPEC:11166-11168 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:11194-11210 | `saw` | fragment | `saw-fragment` | error: undefined type 'UartRegs' |
| SPEC:11256-11269 | `saw` | fragment | `saw-fragment` | error: undefined type 'T' |
| SPEC:11313-11319 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:11388-11405 | `saw` | fragment | `saw-fragment` | error: Parse error at 12:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:11429-11439 | `saw` | fragment-elision | `saw-fragment` | error: Parse error at 3:79: Unexpected token: ELLIPSIS |
| SPEC:11460-11467 | `saw` | fragment | `saw-fragment` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR |
| SPEC:11488-11491 | `saw` | fragment | `saw` — U2: wrap body in `main` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got VAR — WRAPPABLE |
| SPEC:11597-11605 | `saw` | error-demo-UNCONFIRMED | `saw-error`? (see C1) | marked [2], refused at []: error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got LET |
| SPEC:11664-11669 | `saw` | fragment | `saw` — U2: wrap body in `main` | error: Parse error at 1:1: Expected import, export, module, struct, enum, trait, extension, type, extern, or function declaration, got MATCH — WRAPPABLE |
| SPEC:11692-11706 | `saw` | fragment | `saw-fragment` | error: 'SlabHead' is not in the prelude and must be imported |
| SPEC:11736-11802 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:11835-11850 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:11868-11888 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |
| SPEC:11894-11908 | `(bare)` | non-Saw | stay-bare | fence tag (bare) |

---

## Grid (b) — CLAIMS DIFF

### MISSING — a landed feature absent where design 125 requires it

| # | Source | Site | The gap | Evidence |
|---|---|---|---|---|
| **C6** | SKILL.md | `.claude/skills/saw-lang/SKILL.md:2862-2884` (the IMPORT-REQUIRED enumeration) | `std.json` is absent from the skill's prelude-gate list. The list names all 17 other gated modules (file, directory, path, data, channel, mutex, once, time, net, string, task, process, env, fixedbuf, cbor, spinlock, slab, compiler.frame) — json is the only omission. The skill mentions `std.json`/`JsonValue` **zero times in 3,987 lines**. | `.build/scratch/docscensus/C_gated.saw`: ``error: `JsonValue` is not in the prelude and must be imported`` / ``hint: `import std.json.{JsonValue}` selects it…``. `sawc/sawc.py:170` lists `"json"` in `IMPORT_REQUIRED_STD_MODULES` (added by DF-268a). |
| **C7** | README.md | `README.md:407-408` | ``TaskGroup(threads: N)`` is described as an opt-in with no mention that the constructor is **fallible**. Design 234/DF-245a made it return `Result<Self, E>`; the README's own `TaskGroup()` example (`README.md:396`) is the non-threaded form, so a reader following 407 writes code that does not compile. The spec (`LANGUAGE_SPEC.md:7628`) and skill (`SKILL.md:2969-2971`) both spell it `try! TaskGroup(threads: 4)`. | `.build/scratch/docscensus/C_taskgroup_threads.saw` with `var group = TaskGroup(threads: 2)`: ``error: type `Result` has no method `spawn```. |

### WRONG — the doc describes retired or amended behavior (every row has a probe)

| # | Source | Site | The claim | The evidence | My read |
|---|---|---|---|---|---|
| **C4** | **all three** | `LANGUAGE_SPEC.md:11531-11533`, `SKILL.md:2976-2978`, `CLAUDE.md:479` | `Vector.try_copy` is "**the ONE survivor**" / "the one place the retired prefix survives" of design 123's `try_` twins. | `.build/scratch/docscensus/C_trycopy.saw` compiles and runs, printing `1 1 1` — `Vector.try_copy`, **`Map.try_copy`** and **`Set.try_copy`** all exist and all work. Sources: `sawc/std/vector.saw:518`, `sawc/std/map.saw:628`, `sawc/std/set.saw:255`. | **The docs are wrong; the stdlib is right.** All three collections have `copy()` as their `ExplicitCopy` hook, so all three earn the same reporting twin by the spec's own stated reason. The prose needs "the three collection `copy()` twins", not "the one". DF-257b's naming ruling covers all three, not one. |
| **C5** | **all three** | `LANGUAGE_SPEC.md:11154-11158`, `SKILL.md:3312-3314`, `CLAUDE.md:467-472` | The accessor rule, stated as a **quantified rule with a closed enumeration**: "on a safe type every indexed accessor is checked — direct accessors panic out of range (…); a `get`-shaped one returns `None`/`Err` (`Vector.get`, `Data.get`, `Data.slice`)." | `.build/scratch/docscensus/C_fixedbuf_get.saw`, **run**: `in range: 41` then `panic at fixedbuf.saw:55: FixedBuf.get: index out of range: 99 (len 8)`, exit 134. `FixedBuf.get(&self, i: Int) -> Byte` (`sawc/std/fixedbuf.saw:53`) is get-shaped on a safe type and **panics**. | **Safety is intact** (it is checked; nothing is unchecked or silent). What is wrong is the SHAPE half of the rule, which is written as a universal over "a `get`-shaped one" and enumerates three members while a fourth contradicts it. Either the rule is over-quantified (it is really a per-member enumeration) or `FixedBuf.get` is misnamed. Obligation 4 applies: the mechanism is "the accessor rule is prose, enforced by nothing" — no lane checks it — so other members may also diverge. **I did not sweep every std accessor**; see coverage. |
| **C8** | CLAUDE.md | `CLAUDE.md:425-431` (the digest's IMPORT-REQUIRED enumeration) | The gated list reads "File/Data/Channel/Mutex/SpinLock (std.spinlock)/Once (std.once)/slab (std.slab)/net (IoError/IoErrorKind)/Utf8Error/process/env/time (Instant)/fixedbuf/cbor/std.compiler.frame". It omits **`path`, `directory`, `json`** — three of the eighteen gated modules. | `.build/scratch/docscensus/C_gated.saw`, all three refused: ``error: `Path` is not in the prelude and must be imported``, ``error: `Directory` is not in the prelude…``, ``error: `JsonValue` is not in the prelude…``. Ground truth `sawc/sawc.py:171-180`. | **The digest is wrong.** It is orientation-only and owes correctness not coverage — but this is an *enumeration*, and an incomplete enumeration in a digest reads as a complete one. Cheapest fix: three names added. |
| **C9** | CLAUDE.md | `CLAUDE.md:69` ("Compiler usage (dev)") | "That is the complete flag set (`sawc.py:1774-1876`)." | `sawc/sawc.py:1774` is inside `_emit_object()`. The `ArgumentParser` is constructed at `sawc/sawc.py:2040` and the last `add_argument` is `sawc/sawc.py:2142` (`-W`). Verified by `grep -n "add_argument\|ArgumentParser" sawc/sawc.py` (first hit 2040, last 2142) and by reading `sawc/sawc.py:1774-1780`. | **Stale line citation.** The flag *list* in CLAUDE.md is correct (I checked it against `sawc --help`, all 18 flags present and correctly described); only the pointer rotted. Note this is CLAUDE.md's dev-guide half, not the Language-state digest, so it is in scope as a source but outside "orientation-only" cover. |

### INCONSISTENT — two sources disagree

| # | The disagreement | Span A | Span B |
|---|---|---|---|
| **C5** (also above) | The accessor rule's `get`-shaped clause is stated identically in three places and contradicted by a fourth party (the stdlib), so the three docs agree with each other and disagree with `sawc/std/fixedbuf.saw:53`. Recording it here because the fix has to move one of the two sides. | `LANGUAGE_SPEC.md:11154-11158` / `SKILL.md:3312-3314` / `CLAUDE.md:467-472` | `sawc/std/fixedbuf.saw:53` + run evidence in `C_fixedbuf_get.saw` |
| — | **Prelude enumerations disagree in breadth, not in content.** README's curated-core sentence (`README.md:588-597`) omits `Allocator`/`GlobalAllocator`, `Duration` and `Atomic`, which the skill (`SKILL.md:2846-2858`) and CLAUDE.md (`CLAUDE.md:420-426`) both name. README hedges with "and so on", so I record this as prose-level looseness, **not** a finding — flagging it only because U2 may want the lists to converge. | `README.md:588-597` | `SKILL.md:2846-2858` |

### CLEAN — the brief's two priority checks, both confirmed current

Recording these because a negative result from a probe is worth as much as a
positive one, and the evidence rule forbids me leaving "I checked and it was
fine" implicit.

- **Design 234, the `try_` retirement — CLEAN in all four sources.** Method
  of search: `grep -no 'try_[a-z_]*'` over all four files (57 hits) against
  `grep -rn 'func try_' sawc/std/*.saw sawc/builtin.saw` (6 definitions:
  `Channel.try_receive`, `Map.try_copy`, `Once.try_get`, `Set.try_copy`,
  `SpinLock.try_lock`, `Vector.try_copy`). Every doc hit is either one of the
  surviving four names, or sits inside a passage that explicitly says the name
  is RETIRED (`LANGUAGE_SPEC.md:11499-11512`, `SKILL.md:2973-2981`,
  `README.md:221-223`, `CLAUDE.md:475-480`). No doc anywhere calls
  `try_push`/`try_insert`/`try_append`/`try_make`/`try_with_capacity`/`try_send`
  as a live API. The one substantive error is C4 (the "lone survivor" count).
  Blind spot: this is a name-shaped search; a doc that describes the retired
  *behavior* without using a `try_` name would not be caught.
- **Design 242, the Thread/Task split — CLEAN in all four sources.** Method:
  `grep -n 'spawn *{'` over all four. Every occurrence is `Thread.spawn { }`;
  the only bare `spawn { }` texts are the two sentences that say it is GONE
  (`CLAUDE.md:404`, `SKILL.md:1870`, plus `SKILL.md:1899` describing the
  retired `let _ = spawn { … }`). README's fate rule
  (`README.md:450-454`) is probe-confirmed on **both** halves:
  `.build/scratch/docscensus/C_thread_discard.saw` (bare statement) and
  `C_thread_discard2.saw` (`let _ =`) each produce ``error: `Thread.spawn`
  hands back a `Thread<Int>` that must be consumed, and this one is
  discarded``.
- **README's compiler-option block (`README.md:801-832`) is CORRECT AND
  COMPLETE.** All 18 flags in `sawc --help` are present with accurate
  descriptions, and the one warning category it names (`shadowed-qualifier`)
  is the only member of `WARNING_CATEGORIES` (`sawc/errors.py:57-58`).
- **README's "a four-line program links at about 63 KB" (`README.md:51`) is
  ACCURATE.** `.build/scratch/docscensus/C_fourline.saw` links to **63,688
  bytes**.
- **README's bare-`static` claim (`README.md:682-683`) is ACCURATE.**
  `.build/scratch/docscensus/C_bare_statics.saw` declares
  `static HITS: Atomic<Int>`, `static PENDING: SpinLock<Int>`,
  `static REGISTRY: Mutex<Int>`, `static LIMITS: Once<Int>`, compiles, and
  runs printing `1 1 2 7`.
- **The spec's error-demo diagnostic text is CURRENT.** For the 40 blocks
  whose refusal landed within two lines of a doc error-marker, I compared the
  doc's claimed text to the emitted diagnostic
  (`.build/scratch/probe_errmatch2.py`). The matches are near-verbatim —
  e.g. `LANGUAGE_SPEC.md:451` claims ``// error: `main` must return `Void`,
  `Int`, `Result<Void, E>` or`` and sawc emits ``error: `main` must return
  `Void`, `Int`, `Result<Void, E>` or `Result<Int, E>`, but returns
  `String``` — across `main` return types, `Never` bodies, `NoMove`/`NoCopy`
  membership, place windows, escaping-closure capture, `extern blocking`
  C-ABI, static ordering, const-generic bounds, prelude gating, `@section`
  targets, unsafe naming, and the discard rule. **I found no case where a
  spec error demo claims a diagnostic the compiler no longer emits.**
- **`unsafe` is in the post-parameter effect slot everywhere.** All 11 spec
  and 2 skill occurrences of `unsafe {` are `func f(...) unsafe { }`; the
  retired line-level `unsafe { }` block appears only at
  `LANGUAGE_SPEC.md:10918` saying Saw has none.
- **Design 253 (Float↔text) is documented in all three feature docs** —
  `README.md:640-646`, `LANGUAGE_SPEC.md:6344-6396`, `SKILL.md:3824-3864` —
  and the surface it names (`Float.to_string`, `String.to_float`) matches
  `sawc/std/float.saw:1885` and `sawc/std/float.saw:2536`.
- **Design 260 (consuming receivers) is documented** in the spec
  (`LANGUAGE_SPEC.md:3368-3464`, `3694`) and skill (`SKILL.md:544-564`).

### The 38→44 "SUSPECT in older builds" callouts

Per the brief's §4 fence I did **not** re-probe these exhaustively. Where the
census had evidence in hand:

- `SKILL.md:671-677` — "a `&self` receiver arrives BY VALUE … treat the shape
  as caught now and SUSPECT in older builds". **[261-INVALIDATES]** — the
  first half of the sentence is exactly what 261 U3 retires. The *rule* it
  teaches (the receiver is a member of the argument access set) is
  independent of the by-value premise, so 261 will need the premise removed
  without losing the rule.
- `SKILL.md:1721-1724` — "Taking an address needs `&var self`: a `&self`
  receiver arrives BY VALUE". The **first half is CORRECT and stays correct
  regardless of 261**: `FixedBuf.ptr` is declared `&var self` in the stdlib
  (`sawc/std/fixedbuf.saw:48`), which the compiler enforces —
  `.build/scratch/docscensus/C_selfbyvalue.saw` earns ``error: cannot call
  `&var self` method `ptr` on immutable variable `b` ``. Only the *reason
  given* is what 261 retires. **[261-INVALIDATES]** on the reason only.
- The other 41 were not checked. See coverage.

---

## The C-findings

### C1 — `saw-error` as specified is VACUOUS for ~300 of the 440 blocks *(harness design; the highest-value finding for U1)*

**Claim.** The brief's §1 rule "``saw-error``: the lane compiles it and fails
on SUCCESS … without [an `error-contains:` pin], any clean refusal passes"
does not test anything for a block that lacks `main`.

**Evidence.** `sawc` reports ``error: no `main` function found`` for every
main-less input on the hosted path, *in addition to* whatever else it found —
and for many blocks it is the only error. Directly observed at
`.build/scratch/docscensus/SPEC_8956.saw` (whose doc comment claims
``error: struct `Stats` contains NoCopy field `hits` of type `Atomic<Int>` ``):

```
error: no `main` function found
```

…and nothing else. The block's *claimed* diagnostic never fired, yet the
block "refused cleanly" and would pass an exit-code-only `saw-error` lane.
Population: of the 115 blocks carrying an error marker, only **8** refused at
a marked line with no scaffolding noise; **107** did not. Of those 107, **70**
fail with a parse/lex error at line 1-2 (the block is a bare statement
sequence or contains `…`/`...`), so they never reach any semantic check at
all.

**My read.** Not a doc bug and not a compiler bug — a *specification* gap in
the brief. `// error-contains:` must be **mandatory** on `saw-error`, not
optional, and the lane must additionally reject a block whose only
diagnostics are `no main function found` / `Parse error at 1:`. Otherwise the
lane's green is meaningless on the majority of the corpus it counts.

### C2 — `sawc -c` is the mechanism that makes decl-only blocks verifiable *(harness design)*

**Claim.** `-c` (object output, no main required, no link) accepts **72** doc
blocks against **19** for the default hosted spelling — and it does so with
NO edit to the doc text, which is exactly what the brief's "no hidden
scaffolding lines" ruling wants.

**Evidence.** `.build/scratch/probe_dashc.py`, 440 compiles: README 11/23,
SKILL 9/87, SPEC 52/330 accepted with `-c`. The union with the other three
attempts is 92; `-c` alone recovers 72 of the 92, and is the ONLY spelling
that accepts `README.md:433-442` (the `Thread.spawn { compress(9) }` example
over an `extern "C" blocking func compress`), which typechecks and codegens
fine and fails only at LINK:

```
Linking failed: Undefined symbols for architecture arm64:
  "_compress", referenced from:
      ___task_tramp$__closure$main$6_31 in README_433.bin.o
```
```
$ sawc .build/scratch/docscensus/README_433.saw -c -o README_433.o
Compiled .build/scratch/docscensus/README_433.saw -> README_433.o
```

**My read.** A `saw` marker that means "links" strands every example
declaring an `extern` the doc does not define. U1 should either compile the
`saw` marker with `-c` by default, or add a fourth marker for
compiles-but-does-not-link. This is a fact for the lead, not a proposal.

### C3 — 50 fragments are one cheap edit from complete; 20 more need a wrap, not an append *(inventory input for U2)*

**Claim.** The brief asks the census to mark fragments "one cheap edit from a
complete program". There are two distinct cheap edits, and they are not
interchangeable.

**Evidence.** 50 blocks compile when an empty `func main() {}` is APPENDED
(attempt B) — these are top-level declaration sets. A *different* 20 compile
when their body is WRAPPED in `func main { }` (attempt C) — these are bare
statement sequences, and appending a main does nothing for them. Full lists
in grid (a) (`fragment-PROMOTABLE` rows, and rows tagged `WRAPPABLE`). The
wrap set: `SPEC:136, 1131, 2057, 2538, 3111, 3264, 5442, 5499, 6389, 10004,
10423, 10437, 10448, 10476, 10692, 11488, 11664`, `SKILL:851, 1711, 3836`.

Additionally, four blocks are one cheap edit away for a *third* reason — a
missing `import` line that the surrounding prose already supplies:
`SPEC:7555` (needs `import std.net.{TcpStream}` + `import std.channel.{Channel}`),
`SPEC:8034` (needs `import std.net.{TcpListener, TcpStream}`),
`SKILL:1094` (needs the three imports its README twin `README.md:251-263`
already carries and compiles with), `SPEC:8516` (needs `import std.mutex.{Mutex}`).

### C4 — `Vector.try_copy` is not the lone `try_` survivor

See the WRONG table. Probe `.build/scratch/docscensus/C_trycopy.saw`, runs
clean printing `1`/`1`/`1`. Docs wrong, stdlib right.

### C5 — the accessor rule's `get`-shaped clause is contradicted by `FixedBuf.get`

See the WRONG table. Probe `.build/scratch/docscensus/C_fixedbuf_get.saw`,
runs to `panic at fixedbuf.saw:55: FixedBuf.get: index out of range: 99 (len 8)`.
Obligation-4 note: the mechanism is an unenforced prose rule; the sibling
positions are the rest of std's indexed accessors, which I did **not** sweep.

### C6 — the skill's prelude-gate list omits `std.json`

See the MISSING table. Probe `.build/scratch/docscensus/C_gated.saw`.

### C7 — README does not say `TaskGroup(threads:)` is fallible

See the MISSING table. Probe `.build/scratch/docscensus/C_taskgroup_threads.saw`.

**Side observation, not a census finding:** the diagnostic a reader following
README:407 actually gets is ``error: type `Result` has no method `spawn```
with ``hint: no methods defined``, which names neither the fallible
constructor nor `try!`. Whether that is worth a compiler DF is the lead's
call; it is outside 262's scope.

### C8 — the CLAUDE.md digest's gated-module enumeration omits `path`, `directory`, `json`

See the WRONG table. Probe `.build/scratch/docscensus/C_gated.saw`.

### C9 — CLAUDE.md's `sawc.py:1774-1876` flag-set citation is stale

See the WRONG table. The correct span is `sawc/sawc.py:2040-2149`.

### C10 — CLAUDE.md HAS fenced code blocks (the brief says it has none)

**Claim.** The brief's §2 dispatch says "CLAUDE.md has none — confirm".
It has **five** fenced blocks.

**Evidence.** `CLAUDE.md:11-42` (bare fence, the repo map), `CLAUDE.md:52-55`,
`60-68`, `126-129`, `157-163` (all ```` ```bash ````). None contains Saw.

**My read.** No action for U2 beyond "stay-bare" — but U1's extractor must
not assume CLAUDE.md is fence-free, and the §0 risk-ranking line "(542 lines,
no code blocks)" should be corrected when the brief is next touched.

### C11 — the skill has 87 Saw-tagged fences, not 15; and only ONE untagged fence, not "many"

**Claim.** The brief's §0 sizes the skill at "3,987 lines, 15 tagged blocks of
30 fences" and says "many of its fences are UNTAGGED, which the marker
migration must close."

**Evidence.** `grep -c '^\s*```' .claude/skills/saw-lang/SKILL.md` → **176**
fence lines = 88 blocks. `grep -c '^\s*```saw\s*$'` → **87**. Exactly **one**
block is untagged.

**My read.** This changes U1/U2's sizing materially: the migration's job in
the skill is almost entirely *re-tagging* `saw` → `saw-fragment`/`saw-error`
(75 of 87 skill blocks are refused by every spelling), not tagging bare
fences. Corpus total for the lane is **440 blocks**, not the brief's ~350.

---

## [261-INVALIDATES] index

Design 261's U3 retires the `FixedBuf.ptr()` "&self arrives BY VALUE" gotcha
and flips plain aggregate `&self` receivers to by-pointer. Re-check these at
U1/U2 dispatch against post-261 text:

| Where | What 261 touches | Census row this affects |
|---|---|---|
| `LANGUAGE_SPEC.md:3863-3864` | "A `&self` receiver arrives by value, and whether its copy is taken before or after `reset` writes is argument evaluation order." The *rule* (receiver is in the access set) survives; the *premise* does not. | Inventory row `SPEC:3852-3856` and `SPEC:3869-3873` (both `fragment`), claims-diff row for the argument-access-set rule |
| `SKILL.md:671-677` | Same sentence, plus its "SUSPECT in older builds" tail. | Inventory rows `SKILL:664-670`; SUSPECT-currency entry above |
| `SKILL.md:1721-1724` | "Taking an address needs `&var self`: a `&self` receiver arrives BY VALUE, so a pointer built inside such a method addresses the callee's copy." First clause survives (`sawc/std/fixedbuf.saw:48` declares `ptr(&var self)`); the reason is retired. | SUSPECT-currency entry above; probe `C_selfbyvalue.saw` |
| `SKILL.md:3104-3106` | "**a cell-carrying receiver arrives BY POINTER even at `&self`** … Every other `&self` still arrives BY VALUE (the `FixedBuf.ptr()` gotcha)." The second sentence is the one 261 deletes; the first stops being a distinction. | Inventory row `SKILL:3107-3124` (`fragment-PROMOTABLE`) |
| `LANGUAGE_SPEC.md:8878` / `SKILL.md:3116` | The `Counter` / `_at()` worked example that exists to teach the gotcha. | Inventory rows `SPEC:8865-...` (`fragment-PROMOTABLE`), `SKILL:3107-...` (`fragment-PROMOTABLE`) |
| `LANGUAGE_SPEC.md:8448` | `self.region.ptr() as UnsafePointer<UInt8>` inside a `&self` method — may change meaning. | Inventory row for the enclosing block |
| **Whole-corpus** | If 261 changes aggregate `&self` ABI, **every one of the 92 accepted blocks should be re-run** — a by-pointer flip is exactly the kind of change that turns an accepting block into a refusing one. `.build/scratch/probe_compile.py` + `probe_dashc.py` re-run in ~6 minutes. | all |

---

## Coverage — what I did NOT do, and why

1. **I did not re-probe 41 of the 44 "SUSPECT in older builds" callouts.** The
   brief's §4 explicitly excludes an exhaustive re-probe. I checked the three
   for which the census already held evidence (two in the [261-INVALIDATES]
   index, one via `C_selfbyvalue.saw`).
2. **I did not sweep every std indexed accessor for C5's mechanism.** C5 is
   presumed a CLASS under obligation 4 — the mechanism is "an unenforced
   prose rule about method naming" — but enumerating and probing every
   `get`/`set`/`at`/subscript member across 33 std files was beyond this
   dispatch. `FixedBuf.get` is the one I found; there may be siblings. This
   is the single largest gap in my coverage.
3. **I did not verify OUTPUTS.** Per the brief's §4 fence, v1 is compile-only.
   Where a block's comment claims `// prints: 18` or `// 25`, I confirmed only
   that the block compiles (or does not). Four blocks I ran for claims
   evidence are the exception (`C_trycopy`, `C_fixedbuf_get`, `C_bare_statics`,
   `C_fourline`).
4. **I did not read all 11,918 spec lines.** The claims diff is driven by (a)
   the brief's named risk list, (b) the compile probes, and (c) targeted greps
   against the compiler and stdlib. Stale *prose* in a spec section I neither
   probed nor grepped would not be caught. The spec's module table is the one
   part already machine-checked — `tools/test_prelude_gate_doc.py` (the
   `preludegate` battery lane) walks it and asserts every module it marks
   gated is in `IMPORT_REQUIRED_STD_MODULES`, which is why C6/C8 hit the
   skill and CLAUDE.md but NOT the spec. U1 should not duplicate that lane.
5. **I did not check TESTING.md, rt/ABI.md, designs/, or std docstrings.**
   Out of scope per §4.
6. **The 107 "error-demo-UNCONFIRMED" blocks were not individually adjudicated.**
   I characterized the population mechanically (32 near-miss / 70 parse-fail /
   2 cascade / 3 other) and eyeballed the 40 with a diagnostic near a marker.
   Deciding `saw-error` vs `saw-fragment` for the remaining ~75 needs a human
   read of each; that is U2's job, and grid (a) gives every row its
   diagnostic to read from.
7. **`--module-path` blocks were compiled without it.** Several spec blocks
   are multi-file sketches (`SPEC:10248` needs modules `panel`/`knobs`/`facade`;
   others name `parser`, `mymodule`, `kcore`, `shapes`, `dep`,
   `mypkg.collections`). These are correctly `saw-fragment` and no
   `--module-path` invocation could rescue them without inventing files —
   naming the blind spot as the evidence rule requires.
8. **No suite, battery, freestanding, blade-bootstrap or lib test was run.**
   Only 1,664 individual `sawc` invocations. The suite lock was never taken
   and was never needed.
