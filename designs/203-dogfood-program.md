# Design 203 — the dogfood program: naive implementers as instruments

**Status: APPROVED Aug 10 (morning session), scheduled AFTER design 196
lands (running it earlier would rediscover DF-191a/192b/c/193a, already
filed — the concurrency×errors surface it probes is about to change).
The idea: a Sonnet-tier agent writes complete Saw programs from
LANGUAGE-AGNOSTIC specs authored by the lead, reporting every point of
surprise. The weaker model is the better instrument — an expert has
internalized the workarounds and routes around rough edges without
noticing; a competent-but-new reader of the skill and spec approximates
the language's actual future audience. Usability testing by proxy. The
evidence this still pays: DF-191a/190b/192b/192c/193a were ALL found
within 48h by exactly http-server-shaped contact, all in shapes a
normal programmer writes in week one.**

## Priorities [user, Aug 10]

Target where current dogfooding is thinnest:

1. **Task-heavy programs.** The suite's concurrency coverage is
   predominantly single-threaded oracles (counts/sums/teardown), not
   programs. Wave-1 specs: a worker-pool job scheduler with
   cancellation; a producer→transform→sink channel pipeline; an MT
   map-reduce (`threads: N`, real Send discipline); a broadcast/chat
   server (net×tasks); a parallel file search (fs×tasks×MT); a
   rate-limited fetcher (offload×tasks).
2. **Freestanding programs on QEMU virt boards.** Outside the SOS
   kernel, freestanding dogfood is ~zero. Wave-2 specs (riscv32 virt
   first, arm64 virt variants after): UART hello + echo; a CLINT
   timer tick counter; a FixedBuf ring-buffer logger; a slab-backed
   object pool; a panic-path exercise (`--no-hidden-alloc` +
   `{}`-format discipline). The SPEC HANDS THE AGENT A BOARD KIT as
   given material (linker script, entry stub, UART/CLINT addresses —
   extracted from sos/hal, presented as project files, not as things
   to invent): the instrument measures the LANGUAGE's freestanding
   ergonomics, not bare-metal archaeology.

## Protocol

- **Specs are language-agnostic** (behavior, I/O contract, test cases —
  no Saw idioms), authored by the lead; each names its acceptance
  checks. Specs live in `devtools/dogfood/specs/`.
- **The implementer's knowledge is the NEW-USER surface** [user, Aug
  10]: README.md first (the website-shaped entry point), then the
  saw-lang skill, then LANGUAGE_SPEC.md — nothing internal. This puts
  the README under test too: an expectation it sets that the language
  breaks is a reportable finding on the most visible doc we have.
- **The implementer reports, it does not judge.** Every surprise is
  logged with a category — (a) could not express X / needed a
  workaround; (b) an error message misled; (c) the skill/spec is silent
  on X; (d) suspected bug, with minimal repro — and the agent files
  NOTHING itself. "I misread the skill" cases are findings too: a
  skill that misleads a competent reader is a doc bug.
- **The lead triages** every report item, probe-confirms before filing
  (the 190-errata lesson), and disposes each as: DF finding / skill or
  spec edit / working-as-intended (recorded with the reasoning).
- **Outputs compound:** working programs land under
  `devtools/dogfood/programs/` (corpus for the fuzzer, candidates for
  examples/ and bench); failing shapes become cited pins.
- Wave 2 needs a light QEMU runner for standalone freestanding images
  (tools/sos_runner.py boots kernel+root; this is one image + expected
  serial output — a small tool, part of the wave-2 unit).

## Units

1. Wave-1 specs (six, concurrency-weighted) + dispatch on the
   `dogfood` agent type + triage report landed in the tracker.
2. Wave-2 board kit + the standalone QEMU runner + wave-2 specs (five)
   + dispatch + triage.
3. Retrospective: what each wave cost, what it found per token, and
   whether the instrument stays in the standing toolkit (the same
   keep/alter/remove bar as the mech pilot).

## Explicitly out

Letting the implementer file findings or edit the skill (triage is the
lead's); Saw-flavored specs (they smuggle the workarounds in); grading
the implementer's code style (idiom review of KEPT programs happens on
landing, as always — the instrument's job is contact, not elegance).
