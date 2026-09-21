"""The parsed + type-checked stdlib, cached across processes (design 168 unit 4).

Every `sawc` invocation reads, parses and type-checks `builtin.saw` plus all of
`std/` from scratch. With design 168 unit 2 shrinking the back half by ~85%,
that front half is no longer a fifth of a compile — it is roughly two thirds of
one (measured on `hello`: std parse 39%, std type-check 29%, LLVM 5%). This
module replaces it with one `pickle.loads`.

The payload is the `(builtin_ast, builtin_ns)` pair `build_builtin_namespace`
returns, in ONE blob. Never two. Design 164's tier-B audit found that the AST and
the symbol tables SHARE `SawType` objects by identity (106 shared, 0 broken) —
which is what design 144's in-place canonicalization rests on — so two pickles
would restore two graphs that no longer alias, and the symptom is a struct
compiled against another struct's layout with no diagnostic at all.

ORDER IS THE CORRECTNESS CONDITION, not an optimization. `pickle` preserves
`node_id` verbatim while `ASTNode.__deepcopy__` deliberately freshens it, so a
restored std graph carrying ids 1..14,321 collides with whatever the entry file
has already taken. What a collision corrupts is silent: `effects.py` merges two
unrelated functions' suspend analysis under one key, and `coro_transform`'s
`_entry_ext_ids` membership test reclassifies a std extension as user code.
Design 164's first prototype restored the blob inside `load_builtins` — the
obvious place, and after the entry parse — and miscompiled 13 of 1,114 examples,
twelve of them by exit code. So the restore happens BEFORE the entry file is
parsed, and the counter is seeded past the restored graph from a bound stored
beside it. That is O(1); renumbering the restored graph instead costs ~170 ms and
eats most of the win.

THE KEY IS THE PARANOID ONE (design 164 unit 5), because a wrong key is a
stale-cache miscompile:

- Every `.py` under `sawc/`, not a curated subset. A curated subset is precisely
  the bug this key exists to prevent — the day someone edits `lexer.py` and the
  key does not move, the compiler silently uses a stale std. Hashing ~2 MB of
  Python costs a few ms. `rt_build.py` already takes this route.
- ABSOLUTE std paths. `source_file` is baked into every AST node and feeds
  `#file`, design-82 provenance and design-121 docs, so an absolute path makes
  the key self-invalidating across checkouts and across the remote worker's
  unpacked snapshot — which is correct: the worker builds its own cache once per
  sync rather than being handed a blob whose baked paths do not exist there.
- Every flag that changes what is LOADED or what checking MEANS. `freestanding`
  drops the hosted std modules and `runtime_build` loads none; beyond the file
  set, DF-137d makes the TRIPLE change what a checked std is, because platform
  `Int` is pointer-width and a literal that fits on a 64-bit host is a range
  error on riscv32.
- Content-addressed and WRITE-ONCE. Nothing is ever overwritten, so a stale entry
  is impossible by construction; old entries are inert garbage and
  `.build/stdcache/` is disposable. Anchored at the COMPILER checkout via
  `__file__`, never the caller's cwd — blade invokes sawc from arbitrary
  directories, and `rt_build.py` records what a stale scratch file in the wrong
  place once did to every repo-root compile.
- Atomic publish, no lock: write `<key>.tmp.<pid>`, then `os.replace`. A
  partially written blob is never observable, and concurrent processes (the test
  runner's workers) may duplicate the work once but cannot corrupt each other.

NEVER key on a hash of the blob itself. `pickle.dumps` is not byte-stable across
processes — sets serialize in iteration order and `PYTHONHASHSEED` is randomized,
which `tools/irdet.py` deliberately exercises. Key on the SOURCES.
"""

import hashlib
import os
import pickle
import sys

FORMAT_TAG = b"saw-stdcache-v1"

_COMPILER_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(os.path.dirname(_COMPILER_DIR), ".build", "stdcache")

# Set by the environment to turn the cache off — the cold side of the
# differential gate, and the escape hatch if a blob is ever suspected.
_DISABLED = os.environ.get("SAW_NO_STDCACHE") == "1"

# key -> the blob's raw bytes, for a process that compiles more than once (the
# test runner's persistent workers). Bytes only; see `load`.
_BLOB_BYTES: dict = {}


def enabled() -> bool:
    return not _DISABLED


def _compiler_source_digest(h):
    """Fold every `.py` under `sawc/` into the key, path and content both."""
    entries = []
    for root, dirs, files in os.walk(_COMPILER_DIR):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if name.endswith(".py"):
                path = os.path.join(root, name)
                entries.append((os.path.relpath(path, _COMPILER_DIR), path))
    for relpath, path in sorted(entries):
        h.update(relpath.encode())
        with open(path, "rb") as f:
            h.update(f.read())


def cache_key(std_paths, freestanding, runtime_build, target_triple,
              target_features, no_hidden_alloc, optimize):
    """The one key. `std_paths` is exactly the set `load_builtins` would read
    under these flags, absolute and in load order."""
    h = hashlib.sha256()
    h.update(FORMAT_TAG)
    h.update(sys.version.encode())
    h.update(str(pickle.HIGHEST_PROTOCOL).encode())
    _compiler_source_digest(h)
    for flag in (freestanding, runtime_build, no_hidden_alloc, optimize):
        h.update(b"1" if flag else b"0")
    h.update((target_triple or "").encode())
    h.update((target_features or "").encode())
    for path in std_paths:
        h.update(os.path.abspath(path).encode())
        with open(path, "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:16]


def _blob_path(key):
    return os.path.join(CACHE_DIR, f"{key}.blob")


def load(key):
    """Restore `(builtin_ast, builtin_ns)` and seed the node-id counter past it.

    Returns None on a miss, or on ANY failure to read the blob back: a cache is
    an optimization, and a corrupt or version-skewed entry must degrade to a
    cold compile rather than take the build down.

    A blob whose design-206 SEED is not keyed to the AST stored beside it is one
    of those failures (SL-327; codex's SL-318.p6 r1 P2 for the identity half).
    The publication gate keeps new ones off the disk, and this is what makes the
    ones already there cost ONE cold build rather than a silently missing
    diagnostic: it is discarded and DELETED, exactly as an unreadable blob is,
    so the `store` that follows this compile writes a sound one in its place.
    Write-once is why the delete matters — without it `store` would decline
    forever and the key would rebuild cold on every compile.
    """
    path = _blob_path(key)
    try:
        blob = _BLOB_BYTES.get(key)
        if blob is None:
            with open(path, "rb") as f:
                blob = f.read()
            # Hold the BYTES, never the unpickled graph: a compile mutates both
            # halves of the pair (user checking adds methods to the shared `Int`
            # symbol, place lowering rewrites std bodies), so every compile needs
            # its own. The restore IS the reset — which is the whole reason
            # `pickle` beats an incremental "undo what was mutated" scheme.
            _BLOB_BYTES[key] = blob
        builtin_ast, builtin_ns, node_id_bound = pickle.loads(blob)
    except Exception:
        # An unreadable blob cannot arise from a partial write (publication is
        # atomic) or from version skew (the key covers every compiler source and
        # the interpreter). If one appears anyway, DELETE it: write-once means
        # `store` would otherwise decline to replace it and every future compile
        # would silently fall back to a cold build, forever.
        _BLOB_BYTES.pop(key, None)
        try:
            os.unlink(path)
        except OSError:
            pass
        return None

    if not _pair_is_consistent(builtin_ast, builtin_ns):
        # Checked BEFORE the id counter is seeded: this compile is about to
        # build std cold, and seeding past a graph it will not use would waste
        # the id space for nothing.
        _BLOB_BYTES.pop(key, None)
        try:
            os.unlink(path)
        except OSError:
            pass
        return None

    # Seed BEFORE anything else parses. Every id in the restored graph is <= the
    # bound, so the next allocation cannot collide with one.
    from ast_nodes import seed_node_ids
    seed_node_ids(node_id_bound)
    return builtin_ast, builtin_ns


# How many blobs to keep. Each is ~2 MB and the key moves whenever ANY compiler
# source does, so a day of compiler work would otherwise leave a few hundred
# megabytes of dead entries behind.
_KEEP = 8


def _prune():
    """Drop all but the `_KEEP` most recently published blobs.

    Safe to race: unlinking a blob another process has open leaves that process's
    file descriptor valid, and a reader that loses the file mid-open falls back
    to a cold build.
    """
    try:
        blobs = [os.path.join(CACHE_DIR, n) for n in os.listdir(CACHE_DIR)
                 if n.endswith(".blob")]
        for path in sorted(blobs, key=os.path.getmtime, reverse=True)[_KEEP:]:
            os.unlink(path)
    except OSError:
        pass


def seed_identity(entry):
    """The `(owner, method)` a design-206 seed ENTRY is about.

    The entry is `(short, label, line, causes, alt)` and `short` is
    ``` `Owner.method` ``` — the only name-shaped thing it carries, and the
    STABLE identity behind a node id that is only meaningful against one AST
    generation. One reader of that shape, so the publication gate, the repair
    and the diagnostics cannot disagree about what an entry names.
    """
    short = ((entry[0] if entry else None) or "").strip().strip("`")
    owner, _, name = short.rpartition(".")
    return (owner or None, name or None)


def std_method_index(builtin_ast):
    """This std AST's methods, both ways round: `id -> (owner, name)` and
    `(owner, name) -> [ids]`.

    One walk of the std extensions, shared by the publication gate and
    `sawc._rekeyed_std_seed`'s repair — which have to agree about what THIS ast
    holds or the repair would be judged against a different reading than the
    gate that let the blob out.
    """
    by_id = {}
    by_name = {}
    for ext in getattr(builtin_ast, "extensions", None) or ():
        owner = getattr(ext, "struct_name", None)
        for m in getattr(ext, "methods", None) or ():
            nid = getattr(m, "node_id", None)
            if nid is None:
                continue
            ident = (owner, getattr(m, "name", None))
            by_id[nid] = ident
            by_name.setdefault(ident, []).append(nid)
    return by_id, by_name


def unsound_seed_keys(table, builtin_ast):
    """Every design-206 seed key that does not name THE method its entry is
    about, as `key -> why` (SL-327, widened per codex's SL-318.p6 r1 P2).

    The table is keyed by `Method.node_id`, and a node id is only meaningful
    against the AST it was minted in — so a blob whose table and AST are two
    GENERATIONS restores a seed nothing can find. The entry graph's edges then
    name leaf nodes that were never minted, a `sync` violation through a std
    method goes unreported at the settling that would have caught it, and
    because the pipeline stops after a settling that reported errors, any
    compile with another error in it loses that diagnostic silently.

    TWO WAYS A KEY CAN BE WRONG, and the first draft checked only one.
    MEMBERSHIP — the integer names no method here — was the measured face: of
    eight blobs on one developer machine, five were keyed that way, all written
    by a process whose id bound was an order of magnitude past a fresh std
    build's, which is exactly the state `_prepared_builtins`' docstring says the
    pair must not be stored from. But two generations can just as well make an
    integer name the WRONG method: with `Command.output` at 20 here and
    `Command.status` at 10, a stale table keyed 10 for `Command.output` passes a
    membership test, leaves `output` unseeded, and attributes its causes to
    `status` — a MISDIRECTED seed, which is worse than a missing one because the
    wrong method now reports a suspension the std body does not have. So the
    question is IDENTITY, not membership: the entry says which method it is
    about, and the key must name that method.

    Cheap: one walk of the std extensions, once per cache MISS.
    """
    if not table:
        return {}
    by_id, _by_name = std_method_index(builtin_ast)
    bad = {}
    for key, entry in table.items():
        wanted = seed_identity(entry)
        named = by_id.get(key)
        if named is None:
            bad[key] = (f"names no method in this std AST; the entry is about "
                        f"`{wanted[0]}.{wanted[1]}`")
        elif named != wanted:
            bad[key] = (f"names `{named[0]}.{named[1]}` in this std AST, and "
                        f"the entry is about `{wanted[0]}.{wanted[1]}`")
    return bad


def _pair_is_consistent(builtin_ast, builtin_ns):
    """Is this pair's design-206 seed table keyed to THIS ast? (SL-327)

    Both failure modes, because both cost the same diagnostic — see
    `unsound_seed_keys`. Rather than police the callers, the publication checks
    what it is about to publish.
    """
    table = getattr(builtin_ns, "_std_really_suspending_methods", None)
    return not unsound_seed_keys(table, builtin_ast)


def store(key, builtin_ast, builtin_ns):
    """Publish the pair, write-once and atomically. Best effort — a cache that
    cannot be written is not a compile failure.

    SL-327: a pair whose seed table is keyed to a different AST generation is
    NOT published. Declining to write costs one cold std build; writing it costs
    every later compile a diagnostic, silently, until the blob ages out.
    """
    from ast_nodes import current_node_id_bound
    path = _blob_path(key)
    if os.path.exists(path):
        return
    if not _pair_is_consistent(builtin_ast, builtin_ns):
        return
    tmp = f"{path}.tmp.{os.getpid()}"
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        blob = pickle.dumps((builtin_ast, builtin_ns, current_node_id_bound()),
                            protocol=pickle.HIGHEST_PROTOCOL)
        with open(tmp, "wb") as f:
            f.write(blob)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return
    _prune()
