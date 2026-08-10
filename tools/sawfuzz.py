#!/usr/bin/env python3
"""Corpus-mutation fuzzer for sawc (design 192 unit 3).

ONE ORACLE, and it is not "the program is correct": **the compiler either
succeeds or exits with a clean diagnostic.** A Python traceback, an
`internal compiler error`, a crash by signal, or a hang is a finding. Anything
a user can write — including nonsense — deserves an error message with a
location, and the census behind design 190 counted NINE of one week's findings
wearing exactly that face. DF-185a is the poster child: `case Debug = 0x100`,
one token away from an existing test, died in the parser with
`invalid literal for int() with base 10` and no location at all.

WHY MUTATION AND NOT GENERATION. The corpus is 1200+ programs that already
exercise every feature the language has, each one a starting point the compiler
gets deep into before anything goes wrong. A one-token edit of a program that
reaches the coroutine transform still reaches the coroutine transform. A
generated program mostly does not get past the parser. (A grammar-aware
generator is the follow-up if this plateaus — design 192 says so explicitly.)

DETERMINISM IS THE WHOLE VALUE. A finding you cannot replay is a rumour. Every
choice this tool makes comes from `(seed, index)` and nothing else — no
wall-clock, no PID, no `os.urandom`, no set/dict iteration order. Corpus order
is sorted. Mutant `i` is derived from its own RNG (`seed`, `i`), never from the
stream that produced mutant `i-1`, so `--replay-index` reconstructs one mutant
without running the ones before it. The CORPUS is the other input, and it grows:
`--replay-index` reproduces a mutant against the corpus as it stands, so a
finding older than a corpus change replays from its saved `.saw` instead. That
is why the mutant file is written beside the report and not only described.

WAVE-BOUNDED FAN-OUT, FROM DAY ONE. Subprocesses are launched in waves of
`--jobs` and every wave is fully reaped before the next starts. DF-182f was a
fork bomb that took the user's machine to loadavg 700 because a tool lost the
throttle it had been relying on by accident; this one has the throttle on
purpose, and there is no code path that spawns without counting.

    tools/sawfuzz.py --quick             # ~1 minute, the battery mode
    tools/sawfuzz.py --quick 500         # explicit mutant count
    tools/sawfuzz.py --soak              # runs until you stop it
    tools/sawfuzz.py --seed 12345 --quick 200
    tools/sawfuzz.py --replay-index 91 --seed 1      # rebuild ONE mutant
    tools/sawfuzz.py --corpus-filter enum_raw        # narrow the corpus

A finding is written to `--findings` (default `.build/fuzz-findings/`) as three
files: the mutant `.saw`, a DELTA-MINIMIZED `.min.saw`, and a `.txt` holding
the seed, the index, the parent program, the mutation, the exact command, and
the compiler's own output. Findings are deduplicated by failure signature, so a
wave that hits one bug thirty times writes one report and counts the rest.

THE WORKFLOW for a finding is the ordinary one (TESTING.md): file it as a DF,
pin the minimized program in `examples/` under a name that says what BEHAVIOR
it pins, XFAIL it citing the DF, and delete the marker in the landing that
fixes it. Then add its SIGNATURE to `tools/sawfuzz_known.txt`, which is this
tool's XFAIL ledger: a signature listed there is still reported, with its DF
number, but does not fail the run. Without it, one filed-and-unfixed bug would
paint the battery red on every future commit, and a gate everyone has learned
to ignore is worse than no gate. An entry that stops firing is stale exactly as
an XPASS marker is — delete it in the landing that fixes the bug.

Corpus files are skipped when they are not self-contained compiles: `// EXPECT:
skip` (library modules) and `// XFAIL:` (a known-broken program would report
its own known break as a finding on every run). `// COMPILE-FLAGS:` is carried
through, `{TESTDIR}` and all.
"""
import argparse
import os
import random
import re
import shutil
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SAWC = os.path.join(REPO, "sawc", "sawc.py")
DEFAULT_CORPUS = os.path.join(REPO, "examples")
DEFAULT_FINDINGS = os.path.join(REPO, ".build", "fuzz-findings")
WORK_DIR = os.path.join(REPO, ".build", "fuzz-work")

# ---------------------------------------------------------------------------
# The tokenizer.
#
# Deliberately NOT sawc's own lexer: a fuzzer that imports the thing it fuzzes
# breaks whenever that thing breaks, and this one has to keep running against
# an OLD tree (the DF-185a acceptance replay compiles with a pre-design-185
# parser). It is lossless — every character of the source lands in exactly one
# token — so a mutant is the source with one token changed and nothing else.
# ---------------------------------------------------------------------------

TOKEN_RE = re.compile(r"""
    (?P<comment>   //[^\n]*                          )
  | (?P<string>    "(?:\\.|[^"\\\n])*"               )
  | (?P<number>    0[xX][0-9a-fA-F_]+
                 | 0[bB][01_]+
                 | 0[oO][0-7_]+
                 | [0-9][0-9_]*(?:\.[0-9][0-9_]*)?
                                (?:i8|i16|i32|i64|u8|u16|u32|u64)?  )
  | (?P<name>      [A-Za-z_][A-Za-z0-9_]*            )
  | (?P<newline>   \n                                )
  | (?P<space>     [ \t\r]+                          )
  | (?P<op>        <<=|>>=|\.\.=|&&|\|\||==|!=|<=|>=|->|\+=|-=|\*=|/=|%=
                 | &\+|&-|&\*|<<|>>|\.\.|\?\?|\?\.
                 | .                                 )
""", re.VERBOSE)

KEYWORDS = [
    'func', 'let', 'var', 'if', 'else', 'guard', 'return', 'true', 'false',
    'struct', 'extension', 'self', 'init', 'None', 'enum', 'while', 'break',
    'continue', 'case', 'match', 'trait', 'for', 'in', 'type', 'extern',
    'not', 'move', 'unsafe', 'borrows', 'lend', 'as', 'try', 'catch',
    'static', 'public',
]

# Contextual words the parser reads in specific positions only. Substituting
# one in reaches the "keyword where a name belongs" paths that a plain
# identifier swap never does.
CONTEXTUAL = ['import', 'module', 'export', 'package', 'parent', 'sync',
              'escaping', 'blocking', 'const', 'deinit']

TYPE_NAMES = ['Int', 'UInt', 'Int8', 'Int16', 'Int32', 'Int64', 'UInt8',
              'UInt16', 'UInt32', 'UInt64', 'Float', 'Bool', 'String',
              'Vector', 'Map', 'Set', 'Optional', 'Result', 'Box', 'Arc',
              'Data', 'Void', 'Never', 'Self', 'any']

# Operators grouped so a swap lands in the same syntactic slot — an arithmetic
# operator for an arithmetic operator, a comparison for a comparison. Swapping
# across families mostly produces a parse error, which teaches nothing.
OPERATOR_FAMILIES = [
    ['+', '-', '*', '/', '%', '&+', '&-', '&*'],
    ['<', '>', '<=', '>=', '==', '!='],
    ['&&', '||'],
    ['&', '|', '^', '<<', '>>'],
    ['=', '+=', '-=', '*=', '/=', '%=', '<<=', '>>='],
    ['..', '..='],
    ['?', '!'],
    ['?.', '??'],
]

INT_SUFFIXES = ['i8', 'i16', 'i32', 'i64', 'u8', 'u16', 'u32', 'u64']


class Tok:
    __slots__ = ("kind", "text")

    def __init__(self, kind, text):
        self.kind = kind
        self.text = text


def tokenize(src):
    """Split `src` losslessly. ``"".join(t.text for t in tokenize(s)) == s``."""
    out, pos = [], 0
    while pos < len(src):
        m = TOKEN_RE.match(src, pos)
        if m is None:                       # unreachable: `.` matches anything
            out.append(Tok("op", src[pos]))
            pos += 1
            continue
        out.append(Tok(m.lastgroup, m.group()))
        pos = m.end()
    return out


def render(toks):
    return "".join(t.text for t in toks)


# ---------------------------------------------------------------------------
# The mutations. Each takes the token list and a seeded RNG, mutates in place,
# and returns a one-line human description — or None when this program offers
# the mutation no target (a file with no integer literal cannot have one
# rewritten), in which case the driver tries the next mutation for that seed.
# ---------------------------------------------------------------------------

def _pick(rng, xs):
    return xs[rng.randrange(len(xs))]


def _indices(toks, kind, pred=None):
    return [i for i, t in enumerate(toks)
            if t.kind == kind and (pred is None or pred(t.text))]


def mut_token_substitute(toks, rng):
    """Replace one name token with another word from the language's vocabulary.

    Reaches the positions where the parser is deciding what it is looking at:
    a keyword where a name belongs, a type name where a value belongs, a
    contextual word (`import`, `sync`, `const`) out of its one legal position.
    """
    targets = _indices(toks, "name")
    if not targets:
        return None
    i = _pick(rng, targets)
    vocabulary = KEYWORDS + CONTEXTUAL + TYPE_NAMES + sorted(
        {t.text for t in toks if t.kind == "name"})
    replacement = _pick(rng, vocabulary)
    if replacement == toks[i].text:
        return None
    was = toks[i].text
    toks[i] = Tok("name", replacement)
    return f"token-substitute: `{was}` -> `{replacement}`"


def mut_literal_rewrite(toks, rng):
    """Rewrite an integer literal in another of the notations design 50 allows.

    THE DF-185a MUTATION. Every notation is supposed to be interchangeable
    wherever an integer literal is legal — that is the whole point of having
    them — so any position that decodes one by hand instead of through the
    shared decoder breaks the moment a hex literal reaches it. That is exactly
    what an enum raw value did.
    """
    def is_plain_int(s):
        return s.isdigit() or (s.replace("_", "").isdigit() and "." not in s)

    targets = _indices(toks, "number", is_plain_int)
    if not targets:
        return None
    i = _pick(rng, targets)
    was = toks[i].text
    try:
        value = int(was.replace("_", ""))
    except ValueError:
        return None
    forms = [hex(value), bin(value), oct(value).replace("0o", "0o", 1),
             f"{value}{_pick(rng, INT_SUFFIXES)}", f"0x{value:X}"]
    if value >= 10:
        s = str(value)
        forms.append(f"{s[:-3]}_{s[-3:]}" if len(s) > 3 else f"{s[0]}_{s[1:]}")
    new = _pick(rng, forms)
    if new == was:
        return None
    toks[i] = Tok("number", new)
    return f"literal-rewrite: `{was}` -> `{new}`"


def mut_operator_swap(toks, rng):
    """Swap an operator for another in the same family.

    Retypes an expression without breaking its shape, which is how a checker
    path that assumes an operand type gets reached: `a + b` on two Strings,
    `a << b` on two Floats, `a ..= b` where a range was not expected.
    """
    family_of = {}
    for fam in OPERATOR_FAMILIES:
        for op in fam:
            family_of[op] = fam
    targets = [i for i, t in enumerate(toks)
               if t.kind == "op" and t.text in family_of]
    if not targets:
        return None
    i = _pick(rng, targets)
    was = toks[i].text
    new = _pick(rng, family_of[was])
    if new == was:
        return None
    toks[i] = Tok("op", new)
    return f"operator-swap: `{was}` -> `{new}`"


def mut_delete_token(toks, rng):
    """Delete one significant token.

    The cheapest way to reach an error path, and the one that finds crashes in
    recovery: a parser that recovers from a missing `)` by carrying on with a
    half-built node hands the typechecker something no valid program produces.
    """
    targets = [i for i, t in enumerate(toks)
               if t.kind in ("name", "number", "string", "op")]
    if not targets:
        return None
    i = _pick(rng, targets)
    was = toks[i].text
    del toks[i]
    return f"delete-token: `{was}`"


def mut_duplicate_line(toks, rng):
    """Duplicate one line of the program.

    Produces redefinitions, double `return`s, a second `case` for one variant,
    a repeated field — the shapes where a "this is already defined" check
    either fires cleanly or walks off the end of something.
    """
    lines = render(toks).split("\n")
    targets = [i for i, ln in enumerate(lines) if ln.strip()]
    if not targets:
        return None
    i = _pick(rng, targets)
    lines.insert(i + 1, lines[i])
    toks[:] = tokenize("\n".join(lines))
    return f"duplicate-line: line {i + 1} (`{lines[i].strip()[:60]}`)"


def mut_swap_statements(toks, rng):
    """Swap two adjacent statements at the same indentation.

    Use before definition, a `return` before the work, a `lend` before its
    bounds check — order-dependent analyses (the move checkpoint, the effect
    fixpoint, declaration-order const folding) all read differently.
    """
    lines = render(toks).split("\n")
    pairs = []
    for i in range(len(lines) - 1):
        a, b = lines[i], lines[i + 1]
        if not a.strip() or not b.strip():
            continue
        if len(a) - len(a.lstrip()) != len(b) - len(b.lstrip()):
            continue
        if a.rstrip().endswith(("{", "(", "[", ",")) or \
                b.strip().startswith(("}", ")", "]")):
            continue
        pairs.append(i)
    if not pairs:
        return None
    i = _pick(rng, pairs)
    lines[i], lines[i + 1] = lines[i + 1], lines[i]
    toks[:] = tokenize("\n".join(lines))
    return f"swap-statements: lines {i + 1} and {i + 2}"


MUTATIONS = [
    mut_token_substitute,
    mut_literal_rewrite,
    mut_operator_swap,
    mut_delete_token,
    mut_duplicate_line,
    mut_swap_statements,
]


# ---------------------------------------------------------------------------
# The corpus.
# ---------------------------------------------------------------------------

FLAGS_RE = re.compile(r"//\s*COMPILE-FLAGS:\s*(.*)")


def collect_corpus(corpus_dir, name_filter):
    """Every self-contained program in `corpus_dir`, in SORTED order.

    Sorted because a fuzzer whose corpus order depends on the filesystem is not
    reproducible across machines, which is most of what determinism is for.
    """
    entries = []
    for root, dirs, files in os.walk(corpus_dir):
        dirs.sort()
        for name in sorted(files):
            if not name.endswith(".saw"):
                continue
            path = os.path.join(root, name)
            if name_filter and name_filter not in os.path.relpath(path, REPO):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    src = f.read()
            except (OSError, UnicodeDecodeError):
                continue
            head = src[:4000]
            if "// EXPECT: skip" in head:
                continue          # a library module, not a program
            if "// XFAIL:" in head:
                continue          # already broken; it would report its own break
            m = FLAGS_RE.search(head)
            flags = []
            if m:
                flags = m.group(1).replace("{TESTDIR}", corpus_dir).split()
            entries.append((path, src, flags))
    return entries


# ---------------------------------------------------------------------------
# The oracle.
# ---------------------------------------------------------------------------

TRACEBACK_MARK = "Traceback (most recent call last)"
ICE_MARK = "internal compiler error"


def classify(rc, output, timed_out):
    """The one oracle. Returns a short failure kind, or None for "behaved".

    Behaving means: compiled, or refused with a diagnostic. Everything else —
    a traceback, an internal compiler error, a signal, a hang — is a finding,
    whatever the mutant looked like. Nonsense input is still input.
    """
    if timed_out:
        return "hang"
    if TRACEBACK_MARK in output:
        return "traceback"
    if ICE_MARK in output:
        return "internal-compiler-error"
    if rc is not None and rc < 0:
        return f"signal {-rc}"
    if rc not in (0, 1):
        return f"unexpected exit code {rc}"
    return None


KNOWN_FILE = os.path.join(REPO, "tools", "sawfuzz_known.txt")


def load_known(path):
    """The XFAIL ledger: `DF-xxx <TAB> signature` per line, `#` comments.

    Keyed by signature so a known bug reached from a different corpus program
    or a different mutation still matches — the failure is the identity, not
    the route to it.
    """
    known = {}
    if not os.path.exists(path):
        return known
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            df, _, sig = line.partition("\t")
            if not sig:
                continue
            known[sig.strip()] = df.strip()
    return known


EXC_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*(Error|Exception|Interrupt): ")


def signature(kind, output):
    """A stable key for one BUG, so thirty mutants that hit it report once.

    The identity is the failure's own message with everything mutant-specific
    normalized away: numbers (the mutant's file name, every line and column),
    quoted names (a mangled symbol, an identifier the mutation invented). An
    llvmlite refusal carries its real diagnostic on the line AFTER the generic
    `LLVM IR parsing error`, so that line joins the key — otherwise every kind
    of malformed IR would collapse into one entry and the known-findings ledger
    would suppress bugs nobody had ever seen.
    """
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    detail = ""
    anchor = next((i for i, ln in enumerate(lines) if ICE_MARK in ln), None)
    if anchor is not None:
        detail = lines[anchor]
        if anchor + 1 < len(lines):
            detail += " | " + lines[anchor + 1]
    else:
        for ln in reversed(lines):
            if EXC_RE.match(ln):
                detail = ln
                break
        if not detail and lines:
            detail = lines[-1]
    # Paths first: the mutant's own file name is per-index and per-checkout, and
    # a signature carrying one could never be written down in the ledger.
    detail = re.sub(r"[^\s:]*[/\\][^\s:]*\.saw", "<src>", detail)
    detail = re.sub(r"\d+", "N", detail)               # positions, widths
    detail = re.sub(r"'[^']*'", "'X'", detail)         # symbol names
    detail = re.sub(r'"[^"]*"', '"X"', detail)         # LLVM value names
    return f"{kind}: {detail[:220]}"


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class Runner:
    """Compiles one mutant. Object-only: no link, and nothing runnable lands.

    Compiler output is stripped of ANSI colour on the way in: it is read by
    `classify`, keyed by `signature`, and saved into a finding report, and in
    none of those does an escape sequence belong.
    """

    def __init__(self, sawc, timeout, python):
        self.sawc = sawc
        self.timeout = timeout
        self.python = python

    def command(self, src_path, out_path, flags):
        return [self.python, self.sawc, src_path, "-c", "-o", out_path] + flags

    def start(self, src_path, out_path, flags):
        return subprocess.Popen(self.command(src_path, out_path, flags),
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                text=True, cwd=REPO)

    def reap(self, proc, deadline):
        remaining = max(0.1, deadline - time.monotonic())
        try:
            out = proc.communicate(timeout=remaining)[0]
            return proc.returncode, ANSI_RE.sub("", out or ""), False
        except subprocess.TimeoutExpired:
            proc.kill()
            out = proc.communicate()[0]
            return None, ANSI_RE.sub("", out or ""), True

    def run_one(self, src_path, out_path, flags):
        """Synchronous single compile — used by the minimizer and the recheck."""
        proc = self.start(src_path, out_path, flags)
        return self.reap(proc, time.monotonic() + self.timeout)


# ---------------------------------------------------------------------------
# Mutant construction. `(seed, index)` in, one mutant out — nothing else reads.
# ---------------------------------------------------------------------------

def build_mutant(corpus, seed, index):
    """Return `(parent_path, flags, mutated_source, description)` or None.

    The RNG is derived from the seed and the index ALONE, so mutant 91 is the
    same mutant whether it is the 92nd of a soak or the only one of a replay.
    """
    rng = random.Random((seed * 1000003) ^ (index * 2654435761))
    parent_path, src, flags = corpus[index % len(corpus)]
    # Two extra draws so consecutive indices over one parent diverge early.
    rng.random()
    rng.random()
    order = list(range(len(MUTATIONS)))
    rng.shuffle(order)
    for slot in order:
        toks = tokenize(src)
        described = MUTATIONS[slot](toks, rng)
        if described is None:
            continue
        return parent_path, flags, render(toks), described
    return None


# ---------------------------------------------------------------------------
# Minimization: delta-debugging by lines, budget-capped.
# ---------------------------------------------------------------------------

def minimize(runner, source, flags, kind, work_path, out_path, budget=80):
    """Shrink `source` while the failure stays the same KIND.

    Line-granular greedy delta debugging: try dropping a run of lines, keep the
    drop if the compiler still fails the same way, halve the run when it does
    not. Capped at `budget` compiles — a minimized repro is a convenience, and
    an uncapped minimizer on a 400-line program costs more than the fuzzing.
    """
    lines = source.split("\n")
    spent = 0

    def still_fails(candidate):
        nonlocal spent
        spent += 1
        with open(work_path, "w", encoding="utf-8") as f:
            f.write(candidate)
        rc, out, timed_out = runner.run_one(work_path, out_path, flags)
        return classify(rc, out, timed_out) == kind

    chunk = max(1, len(lines) // 2)
    while chunk >= 1 and spent < budget:
        i = 0
        changed = False
        while i < len(lines) and spent < budget:
            candidate = lines[:i] + lines[i + chunk:]
            if candidate and still_fails("\n".join(candidate)):
                lines = candidate
                changed = True
            else:
                i += chunk
        if not changed:
            if chunk == 1:
                break
            chunk //= 2
    return "\n".join(lines), spent


# ---------------------------------------------------------------------------
# The driver.
# ---------------------------------------------------------------------------

class Findings:
    def __init__(self, directory):
        self.dir = directory
        self.by_signature = {}
        self.total = 0

    def record(self, sig, report, mutant_src, minimized, stem):
        self.total += 1
        if sig in self.by_signature:
            self.by_signature[sig]["count"] += 1
            return False
        os.makedirs(self.dir, exist_ok=True)
        base = os.path.join(self.dir, stem)
        with open(base + ".saw", "w", encoding="utf-8") as f:
            f.write(mutant_src)
        with open(base + ".min.saw", "w", encoding="utf-8") as f:
            f.write(minimized)
        with open(base + ".txt", "w", encoding="utf-8") as f:
            f.write(report)
        self.by_signature[sig] = {"count": 1, "stem": stem}
        return True


def fuzz(args):
    corpus = collect_corpus(args.corpus, args.corpus_filter)
    if not corpus:
        print(f"sawfuzz: no corpus programs under {args.corpus}"
              + (f" matching `{args.corpus_filter}`" if args.corpus_filter else ""),
              file=sys.stderr)
        return 2

    runner = Runner(args.sawc, args.timeout, sys.executable)
    findings = Findings(args.findings)
    known = {} if args.ignore_known else load_known(args.known)
    known_hits = {}
    os.makedirs(WORK_DIR, exist_ok=True)

    total = args.count
    unbounded = total is None
    print(f"sawfuzz: seed {args.seed}, {len(corpus)} corpus program(s), "
          f"{'soak (unbounded)' if unbounded else f'{total} mutant(s)'}, "
          f"waves of {args.jobs}")

    started = time.monotonic()
    index = 0
    compiled = 0
    skipped = 0
    new_findings = 0

    while unbounded or index < total:
        wave_size = args.jobs if unbounded else min(args.jobs, total - index)
        wave = []
        for _ in range(wave_size):
            built = build_mutant(corpus, args.seed, index)
            i = index
            index += 1
            if built is None:
                skipped += 1
                continue
            parent, flags, mutant_src, described = built
            work = os.path.join(WORK_DIR, f"m{i}.saw")
            out = os.path.join(WORK_DIR, f"m{i}.o")
            with open(work, "w", encoding="utf-8") as f:
                f.write(mutant_src)
            wave.append({"index": i, "parent": parent, "flags": flags,
                         "src": mutant_src, "how": described,
                         "work": work, "out": out})

        # WAVE-BOUNDED: exactly `len(wave)` processes exist at once, and every
        # one is reaped before the next wave starts. This is the DF-182f rule.
        deadline = time.monotonic() + args.timeout
        for item in wave:
            item["proc"] = runner.start(item["work"], item["out"], item["flags"])
        for item in wave:
            item["rc"], item["out_text"], item["timed_out"] = \
                runner.reap(item["proc"], deadline)
        compiled += len(wave)

        for item in wave:
            kind = classify(item["rc"], item["out_text"], item["timed_out"])
            if kind is None:
                continue
            # Attribution check: if the UNMUTATED parent fails the same way,
            # the mutation found nothing — the corpus program was already
            # broken (a pin whose XFAIL marker was removed, a tree mid-edit).
            rc, out, to = runner.run_one(item["parent"], item["out"], item["flags"])
            if classify(rc, out, to) == kind:
                print(f"  note: {os.path.relpath(item['parent'], REPO)} already "
                      f"fails this way UNMUTATED ({kind}) — not a fuzz finding")
                continue

            sig = signature(kind, item["out_text"])
            if sig in known:
                # Filed, pinned, not yet fixed. Reported so it stays visible,
                # not fatal so the gate stays worth reading.
                known_hits[sig] = known_hits.get(sig, 0) + 1
                continue
            minimized, spent = minimize(
                runner, item["src"], item["flags"], kind,
                os.path.join(WORK_DIR, f"min{item['index']}.saw"),
                os.path.join(WORK_DIR, f"min{item['index']}.o"))
            stem = f"seed{args.seed}-i{item['index']}"
            report = (
                f"sawfuzz finding\n"
                f"===============\n"
                f"kind:      {kind}\n"
                f"signature: {sig}\n"
                f"seed:      {args.seed}\n"
                f"index:     {item['index']}\n"
                f"parent:    {os.path.relpath(item['parent'], REPO)}\n"
                f"mutation:  {item['how']}\n"
                f"replay:    tools/sawfuzz.py --seed {args.seed} "
                f"--replay-index {item['index']}\n"
                f"command:   {' '.join(runner.command('<mutant>.saw', '<out>.o', item['flags']))}\n"
                f"minimized: {len(minimized.splitlines())} of "
                f"{len(item['src'].splitlines())} lines, {spent} probe compile(s)\n"
                f"\n--- compiler output ---\n{item['out_text']}\n")
            if findings.record(sig, report, item["src"], minimized, stem):
                new_findings += 1
                print(f"  FINDING [{kind}] {stem} "
                      f"(from {os.path.basename(item['parent'])}: {item['how']})")
                print(f"           {sig}")

        if unbounded and args.soak_report and \
                compiled % (args.jobs * args.soak_report) < args.jobs:
            print(f"  ... {compiled} mutants, {new_findings} distinct finding(s), "
                  f"{time.monotonic() - started:.0f}s")

    elapsed = time.monotonic() - started
    for sig, count in known_hits.items():
        print(f"  known [{known[sig]}] x{count}  {sig}")
    print(f"sawfuzz: {compiled} mutant(s) in {elapsed:.1f}s "
          f"({compiled / max(elapsed, 0.001):.1f}/s), {skipped} unmutatable, "
          f"{sum(known_hits.values())} known hit(s), "
          f"{findings.total} failing compile(s) in "
          f"{len(findings.by_signature)} distinct NEW finding(s)")
    if findings.by_signature:
        print(f"\nWritten to {os.path.relpath(findings.dir, REPO)}:")
        for sig, info in findings.by_signature.items():
            print(f"  {info['stem']}  x{info['count']}  {sig}")
        print("\nEach finding is a DF: file it, pin the .min.saw in examples/ "
              "under a behavior name,\nXFAIL it citing the DF, and delete the "
              "marker in the landing that fixes it.")
        return 1
    return 0


def replay(args):
    """Rebuild ONE mutant and compile it, printing everything."""
    corpus = collect_corpus(args.corpus, args.corpus_filter)
    built = build_mutant(corpus, args.seed, args.replay_index)
    if built is None:
        print(f"sawfuzz: seed {args.seed} index {args.replay_index} produced no "
              f"mutant (the parent offered no mutation a target)")
        return 2
    parent, flags, mutant_src, described = built
    os.makedirs(WORK_DIR, exist_ok=True)
    work = os.path.join(WORK_DIR, f"replay{args.replay_index}.saw")
    with open(work, "w", encoding="utf-8") as f:
        f.write(mutant_src)
    print(f"parent:   {os.path.relpath(parent, REPO)}")
    print(f"mutation: {described}")
    print(f"mutant:   {os.path.relpath(work, REPO)}")
    runner = Runner(args.sawc, args.timeout, sys.executable)
    rc, out, timed_out = runner.run_one(
        work, os.path.join(WORK_DIR, "replay.o"), flags)
    kind = classify(rc, out, timed_out)
    print(f"verdict:  {kind or 'behaved (compiled, or refused cleanly)'}")
    print(f"\n--- compiler output (rc={rc}) ---\n{out}")
    return 1 if kind else 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--quick", nargs="?", type=int, const=150,
                      metavar="N",
                      help="N mutants (default 150, about a minute at ~2-3 "
                           "compiles/s) — the battery mode")
    mode.add_argument("--soak", action="store_true",
                      help="run until interrupted (manual / overnight)")
    mode.add_argument("--replay-index", type=int, metavar="I",
                      help="rebuild and compile mutant I of this seed, alone")
    ap.add_argument("--seed", type=int, default=1,
                    help="the ONLY source of variation (default 1)")
    ap.add_argument("--jobs", type=int, default=min(8, (os.cpu_count() or 4)),
                    help="wave width — processes alive at once (default "
                         "min(8, cpus)); every wave is reaped before the next")
    ap.add_argument("--corpus", default=DEFAULT_CORPUS,
                    help="corpus directory (default examples/)")
    ap.add_argument("--corpus-filter", default=None, metavar="SUBSTRING",
                    help="only corpus paths containing SUBSTRING")
    ap.add_argument("--findings", default=DEFAULT_FINDINGS,
                    help="where findings are written "
                         "(default .build/fuzz-findings/)")
    ap.add_argument("--sawc", default=DEFAULT_SAWC,
                    help="the sawc.py to fuzz (default this tree's) — an older "
                         "one replays a historical bug")
    ap.add_argument("--timeout", type=float, default=90.0,
                    help="per-compile seconds; exceeding it is a HANG finding")
    ap.add_argument("--known", default=KNOWN_FILE,
                    help="the XFAIL ledger of filed-but-unfixed signatures "
                         "(default tools/sawfuzz_known.txt)")
    ap.add_argument("--ignore-known", action="store_true",
                    help="report the ledger's entries as new findings too — "
                         "how you check whether a filed one is fixed")
    ap.add_argument("--soak-report", type=int, default=25, metavar="WAVES",
                    help="progress line every N waves under --soak")
    ap.add_argument("--clean", action="store_true",
                    help="empty the findings directory first")
    args = ap.parse_args()

    if args.clean and os.path.isdir(args.findings):
        shutil.rmtree(args.findings)

    if args.replay_index is not None:
        return replay(args)

    args.count = None if args.soak else (args.quick if args.quick else 150)
    return fuzz(args)


if __name__ == "__main__":
    sys.exit(main())
