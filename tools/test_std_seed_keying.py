#!/usr/bin/env python3
"""design 275 U2 — THE STD SEED KEYING GATE (`stdseed`).

SL-327, widened by codex's SL-318.p6 r1 P2. The design-206 seed table
(`_std_really_suspending_methods`) is keyed by `Method.node_id`, and a node id
means nothing against a different AST generation. When the key is wrong the
compile does not fail — it loses a DIAGNOSTIC: the leaf the entry graph's edges
look for is never minted, a `sync` violation reached through a std method goes
unreported at the settling that would have caught it, and because the pipeline
stops after a settling that reported errors, any compile with another error in
it loses that diagnostic silently.

That is a failure nothing in the corpus can see — the programs still compile,
and the only visible cell is the two-violation test, which needs a bad blob on
the machine to fail. So the rules are checked directly, as a unit:

  1. A SOUND table is left alone, and the repair returns the very object it was
     given (a fresh std build must pay nothing).
  2. A WRONG-METHOD-ID key — the integer exists but names another method — is
     unsound and RE-KEYS onto the method its entry is about. This is the case
     the first draft missed: it tested MEMBERSHIP, so a stale key that landed on
     a sibling passed, the real method stayed unseeded, and its causes were
     attributed to the sibling. A misdirected seed is worse than a missing one.
  3. A MISSING-ID key is unsound and re-keys the same way.
  4. An UNRESOLVABLE identity — no method of that `(owner, name)` anywhere in
     this std AST — is an INVARIANT FAILURE naming the entry, never a silently
     dropped seed.
  5. PUBLICATION refuses a pair with either kind of bad key, so a bad blob is
     not written in the first place.
  6. LOADING discards AND DELETES one that is already on disk, so it costs one
     cold std build rather than a silently missing diagnostic forever
     (publication is write-once, so without the delete the key would rebuild
     cold on every compile). A SOUND blob loads back, which is what says the
     discard is about soundness and not about everything.

Run from the repo root:  ./.venv/bin/python tools/test_std_seed_keying.py
Exit code 0 = pass; nonzero (with a diagnostic) = fail.
"""

import contextlib
import io
import os
import pickle
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SAWC = os.path.join(REPO, "sawc")

sys.path.insert(0, SAWC)

import stdcache                                               # noqa: E402
import sawc                                                   # noqa: E402


# --------------------------------------------------------------------------- #
# the fixture: codex's own numbers
# --------------------------------------------------------------------------- #
#
# `Command.output` is node 20 and `Command.status` is node 10 — so a stale table
# keyed 10 for `Command.output` names a real method that is the WRONG one, which
# is exactly the shape a membership test cannot see. Module-level classes
# because check 6 pickles them.

class FakeMethod:
    def __init__(self, name, node_id):
        self.name = name
        self.node_id = node_id


class FakeExtension:
    def __init__(self, struct_name, methods):
        self.struct_name = struct_name
        self.methods = methods


class FakeAst:
    def __init__(self, extensions):
        self.extensions = extensions


class FakeNamespace:
    def __init__(self, table):
        self._std_really_suspending_methods = table


def _ast():
    return FakeAst([FakeExtension("Command", [FakeMethod("status", 10),
                                              FakeMethod("output", 20)])])


def _entry(owner, name):
    """One seed entry, in the shape `build_builtin_namespace` mints:
    `(short, label, line, causes, alt)`."""
    return (f"`{owner}.{name}`", "cooperative park", 12, 1, None)


# --------------------------------------------------------------------------- #
# 1-4: the repair
# --------------------------------------------------------------------------- #

def check_sound_table_is_untouched():
    table = {10: _entry("Command", "status"), 20: _entry("Command", "output")}
    problems = []
    bad = stdcache.unsound_seed_keys(table, _ast())
    if bad:
        problems.append(
            f"a table whose every key names its own method is reported "
            f"unsound: {bad}")
    if not stdcache._pair_is_consistent(_ast(), FakeNamespace(table)):
        problems.append("a sound pair is refused at publication.")
    got = sawc._rekeyed_std_seed(table, _ast())
    if got is not table:
        problems.append(
            "a sound table is REBUILT rather than returned unchanged — a "
            "fresh std build must pay nothing for this repair.")
    return problems


def check_wrong_method_id_is_rekeyed():
    # The key 10 exists in the AST, and it is `Command.status`. The entry is
    # about `Command.output`, which lives at 20.
    table = {10: _entry("Command", "output")}
    problems = []
    bad = stdcache.unsound_seed_keys(table, _ast())
    if 10 not in bad:
        problems.append(
            "a key naming the WRONG method passes the soundness check. That "
            "is membership, not identity: the real method stays unseeded and "
            "its causes are attributed to the sibling the integer landed on.")
    else:
        for want in ("Command.status", "Command.output"):
            if want not in bad[10]:
                problems.append(
                    f"the wrong-method report does not name `{want}`: "
                    f"{bad[10]}")
    if stdcache._pair_is_consistent(_ast(), FakeNamespace(table)):
        problems.append(
            "a pair whose key names the wrong method is PUBLISHED. Both kinds "
            "of bad key cost the same diagnostic, so both are gated.")
    got = sawc._rekeyed_std_seed(table, _ast())
    if got != {20: table[10]}:
        problems.append(
            f"a wrong-method key was not re-keyed onto `Command.output`'s own "
            f"id (20): {got}")
    return problems


def check_missing_id_is_rekeyed():
    table = {99: _entry("Command", "output")}
    problems = []
    if 99 not in stdcache.unsound_seed_keys(table, _ast()):
        problems.append("a key naming no method at all passes the check.")
    if stdcache._pair_is_consistent(_ast(), FakeNamespace(table)):
        problems.append("a pair with a key naming no method is PUBLISHED.")
    got = sawc._rekeyed_std_seed(table, _ast())
    if got != {20: table[99]}:
        problems.append(
            f"a missing-id key was not re-keyed onto `Command.output`'s own "
            f"id (20): {got}")
    return problems


def check_unresolvable_identity_is_an_invariant_failure():
    table = {10: _entry("Command", "nonesuch")}
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            got = sawc._rekeyed_std_seed(table, _ast())
    except SystemExit as e:
        text = err.getvalue()
        problems = []
        if e.code == 0:
            problems.append("the invariant failure exited 0.")
        if "internal compiler error" not in text:
            problems.append(
                f"an unresolvable seed identity does not report as an "
                f"internal compiler error: {text!r}")
        if "Command.nonesuch" not in text:
            problems.append(
                f"the invariant failure does not NAME the entry it could not "
                f"place: {text!r}")
        return problems
    return [f"an unresolvable seed identity was silently dropped "
            f"(returned {got!r}) — that is the lost diagnostic this repair "
            f"exists to prevent, moved one step later."]


# --------------------------------------------------------------------------- #
# 6: the load-time fallback
# --------------------------------------------------------------------------- #

def _write_blob(key, table):
    with open(stdcache._blob_path(key), "wb") as fh:
        pickle.dump((_ast(), FakeNamespace(table), 0), fh,
                    protocol=pickle.HIGHEST_PROTOCOL)


def check_load_discards_and_deletes_an_unsound_blob():
    scratch = os.path.join(REPO, ".build", "scratch", "stdseed_cache")
    shutil.rmtree(scratch, ignore_errors=True)
    os.makedirs(scratch, exist_ok=True)
    saved_dir = stdcache.CACHE_DIR
    saved_bytes = dict(stdcache._BLOB_BYTES)
    problems = []
    try:
        stdcache.CACHE_DIR = scratch
        stdcache._BLOB_BYTES.clear()

        _write_blob("badkey", {10: _entry("Command", "output")})
        if stdcache.load("badkey") is not None:
            problems.append(
                "an unsound blob was RESTORED. Its seed cannot be found by the "
                "entry graph's edges, so the compile loses a diagnostic and "
                "says nothing.")
        if os.path.exists(stdcache._blob_path("badkey")):
            problems.append(
                "an unsound blob was discarded but not DELETED. Publication is "
                "write-once, so it would be rejected again on every compile of "
                "that key, forever.")

        _write_blob("goodkey", {10: _entry("Command", "status"),
                                20: _entry("Command", "output")})
        if stdcache.load("goodkey") is None:
            problems.append(
                "a SOUND blob was discarded too — the control that says the "
                "discard is about soundness and not about everything.")
        if not os.path.exists(stdcache._blob_path("goodkey")):
            problems.append("a sound blob was deleted.")
    finally:
        stdcache.CACHE_DIR = saved_dir
        stdcache._BLOB_BYTES.clear()
        stdcache._BLOB_BYTES.update(saved_bytes)
        shutil.rmtree(scratch, ignore_errors=True)
    return problems


def main():
    problems = []
    problems += check_sound_table_is_untouched()
    problems += check_wrong_method_id_is_rekeyed()
    problems += check_missing_id_is_rekeyed()
    problems += check_unresolvable_identity_is_an_invariant_failure()
    problems += check_load_discards_and_deletes_an_unsound_blob()

    if problems:
        print("STD SEED KEYING GATE FAILED")
        print()
        for p in problems:
            print(f"  {p}")
        print()
        print("A cached std seed key must name the METHOD ITS ENTRY IS ABOUT —")
        print("membership of the integer is not the question (SL-327).")
        return 1

    print("std-seed keying gate: a sound table is untouched, a wrong-method "
          "key and a missing key are both refused at publication and re-keyed "
          "by identity, an unresolvable identity is an invariant failure "
          "naming the entry, and an unsound blob on disk is discarded and "
          "deleted while a sound one loads.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
