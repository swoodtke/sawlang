"""`saw tasks` / `saw bt` — logical task backtraces under lldb (design 158).

A stopped Saw program's live tasks are not on any thread stack: a suspended
task is one heap allocation holding its root coroutine frame, with every
suspending callee's frame embedded by value inside it. A native backtrace of a
parked process shows the executor's poll loop and nothing about what the
program is actually waiting for. This reconstructs the LOGICAL stacks — Go's
goroutine dump is the model.

    (lldb) command script import tools/lldb_saw.py
    (lldb) saw tasks
    (lldb) saw bt

Everything it needs is in the binary. `__saw_bt_table` (design 158 unit 1)
carries, per monomorphized frame, the byte offset of its `__state` word and,
per resume state, either the source line the frame is parked on or the embedded
child it is inside plus that child's offset. The same blob's runtime descriptor
carries the handful of executor offsets a debugger cannot otherwise know, since
Saw emits line tables and no type information (design 69). So the walk is a
static table lookup from one address, and this script hard-codes no layout.

READ-ONLY, and deliberately so (the design-158 v1 fences): it decodes where
each task is parked, never what its variables hold, and it never steps, resumes
or writes anything. The process is stopped under the debugger, so the walk sees
a consistent snapshot with no synchronization of its own.
"""

import os
import struct
import sys

try:
    import lldb
except ImportError:                                          # pragma: no cover
    lldb = None

_SAWC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "sawc")
if _SAWC not in sys.path:
    sys.path.insert(0, _SAWC)

# The encoding lives with the encoder — importing the compiler's own reader is
# what keeps this script from drifting away from the bytes it is handed.
from backtrace_table import decode as _decode_table          # noqa: E402

TABLE_SYMBOL = "__saw_bt_table"
VTABLES_SYMBOL = "__saw_bt_vtables"
MAX_DEPTH = 64


class SawError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Target reading
# --------------------------------------------------------------------------- #

def _target(debugger, need_process=True):
    target = debugger.GetSelectedTarget()
    if not target or not target.IsValid():
        raise SawError("no target")
    process = target.GetProcess()
    if not process or not process.IsValid():
        if need_process:
            raise SawError("no running process — `run` first, then stop")
        process = None
    return target, process


def _symbol_address(target, name):
    """The load address of `name`, or None.

    Tried bare and with a leading underscore: Mach-O prefixes every C symbol,
    ELF does not, and the same script serves both.
    """
    for candidate in (name, "_" + name):
        symbols = target.FindSymbols(candidate)
        for i in range(symbols.GetSize()):
            symbol = symbols.GetContextAtIndex(i).GetSymbol()
            if not symbol.IsValid():
                continue
            addr = symbol.GetStartAddress().GetLoadAddress(target)
            if addr != lldb.LLDB_INVALID_ADDRESS:
                return addr
    return None


def _symbol_present(target, name):
    """Is `name` in this target at all?

    Separate from `_symbol_address` because a load address only exists once
    there is a process, and `saw table` deliberately runs before `run`.
    """
    for candidate in (name, "_" + name):
        symbols = target.FindSymbols(candidate)
        for i in range(symbols.GetSize()):
            if symbols.GetContextAtIndex(i).GetSymbol().IsValid():
                return True
    return False


def _symbol_extent(target, name):
    for candidate in (name, "_" + name):
        symbols = target.FindSymbols(candidate)
        for i in range(symbols.GetSize()):
            symbol = symbols.GetContextAtIndex(i).GetSymbol()
            if not symbol.IsValid():
                continue
            start = symbol.GetStartAddress().GetLoadAddress(target)
            end = symbol.GetEndAddress().GetLoadAddress(target)
            if start != lldb.LLDB_INVALID_ADDRESS and end > start:
                return start, end - start
    return None, 0


class _Reader:
    def __init__(self, process, word_bytes):
        self.process = process
        self.word_bytes = word_bytes

    def bytes(self, addr, size):
        err = lldb.SBError()
        data = self.process.ReadMemory(addr, size, err)
        if not err.Success():
            raise SawError(f"cannot read {size} bytes at {addr:#x}: {err}")
        return data

    def word(self, addr):
        raw = self.bytes(addr, self.word_bytes)
        return int.from_bytes(raw, "little", signed=True)

    def byte(self, addr):
        return self.bytes(addr, 1)[0]


# --------------------------------------------------------------------------- #
# The table
# --------------------------------------------------------------------------- #

def _section_bytes(target, name):
    """The table read out of the FILE, for a target with no process.

    `saw table` works before `run`, and on a core-less target, because the blob
    is read-only data that says the same thing loaded or not.
    """
    for candidate in (name, "_" + name):
        symbols = target.FindSymbols(candidate)
        for i in range(symbols.GetSize()):
            symbol = symbols.GetContextAtIndex(i).GetSymbol()
            if not symbol.IsValid():
                continue
            start = symbol.GetStartAddress()
            section = start.GetSection()
            if not section.IsValid():
                continue
            size = symbol.GetEndAddress().GetFileAddress() - start.GetFileAddress()
            if size <= 0:
                continue
            data = section.GetSectionData()
            err = lldb.SBError()
            raw = data.ReadRawData(
                err, start.GetFileAddress() - section.GetFileAddress(), size)
            if err.Success():
                return raw
    return None


def _load_table(target, process):
    addr, size = _symbol_extent(target, TABLE_SYMBOL)
    if addr is None or process is None or not process.IsValid():
        blob = _section_bytes(target, TABLE_SYMBOL)
        if blob is None:
            raise SawError(
                f"`{TABLE_SYMBOL}` is not in this target — it is not a Saw "
                f"binary, or it was built by a compiler older than design 158")
        return _decode_table(blob)
    err = lldb.SBError()
    blob = process.ReadMemory(addr, size, err)
    if not err.Success():
        raise SawError(f"cannot read the backtrace table: {err}")
    return _decode_table(blob)


def _vtable_index(target, reader, table):
    """vtable address -> frame index.

    A live task is an erased `Box<any Resumable>`, so the vtable word beside its
    data pointer names its frame TYPE — and that is the one thing the walk
    cannot read out of the frame itself. The in-process walker asks the vtable
    directly (`__bt_desc`); a debugger must not run code in the target, so the
    compiler writes the map down as `__saw_bt_vtables`, a pointer per frame in
    table order (design 158). Matching by vtable SYMBOL is not an option: those
    globals are private and the linker drops their names.
    """
    base = _symbol_address(target, VTABLES_SYMBOL)
    if base is None or reader is None:
        return {}
    out = {}
    for index in range(len(table["frames"])):
        try:
            addr = reader.word(base + index * reader.word_bytes)
        except SawError:
            break
        if addr:
            out[addr] = index
    return out


def _walk(table, reader, index, base):
    """The logical stack of one task, OUTERMOST first.

    Each step reads the frame's `__state` word and asks the table what that
    state means: a line (this frame is the leaf — it is parked there) or a
    child at a known offset (this frame is inside a call, so print the call's
    line and descend). Bounded by `MAX_DEPTH` so a corrupt or half-written
    frame produces a truncated dump rather than a hung debugger.
    """
    frames = table["frames"]
    out = []
    seen = set()
    for _ in range(MAX_DEPTH):
        if index < 0 or index >= len(frames):
            out.append((None, 0, base, "unknown frame type"))
            return out
        frame = frames[index]
        state = reader.word(base + frame["state_field"])
        note = ""
        line = 0
        child = -1
        child_off = 0
        if 0 <= state < len(frame["states"]):
            entry = frame["states"][state]
            line, child, child_off = (entry["line"], entry["child"],
                                      entry["child_offset"])
        else:
            note = f"state {state} (completed or not yet started)"
        out.append((frame, line, base, note))
        if child < 0:
            return out
        base += child_off
        if base in seen:
            out.append((None, 0, base, "frame cycle — table or memory is bad"))
            return out
        seen.add(base)
        index = child
    out.append((None, 0, base, f"stack deeper than {MAX_DEPTH} frames"))
    return out


def _wake_text(remaining):
    if remaining < 0:
        return "io-parked"
    if remaining == 0:
        return "ready"
    return f"sleeping {remaining}ns"


# --------------------------------------------------------------------------- #
# The executor walk
# --------------------------------------------------------------------------- #

def _tasks(target, process, table):
    desc = table["exec"]
    if desc is None:
        return []
    head_addr = _symbol_address(target, desc["head_symbol"])
    if head_addr is None:
        raise SawError(f"the task-list head `{desc['head_symbol']}` is not in "
                       f"this target")
    reader = _Reader(process, table["word_bits"] // 8)
    vtables = _vtable_index(target, reader, table)

    def vector(group, field_off):
        ptr = reader.word(group + field_off + desc["vec_ptr_off"])
        length = reader.word(group + field_off + desc["vec_len_off"])
        return ptr, length

    out = []
    group = reader.word(head_addr)
    group_number = 0
    seen_groups = set()
    while group and group not in seen_groups:
        seen_groups.add(group)
        group_number += 1
        tasks_ptr, count = vector(group, desc["off_tasks"])
        done_ptr, _ = vector(group, desc["off_done"])
        gen_ptr, _ = vector(group, desc["off_gen"])
        rem_ptr, _ = vector(group, desc["off_remaining"])
        active_ptr, _ = vector(group, desc["off_active"])
        workers = reader.word(group + desc["off_workers"])
        word = reader.word_bytes
        for slot in range(count):
            # design 134: a completed task's slot holds no frame at all, and a
            # recycled slot carries a retired generation. Skipping both is what
            # keeps a stale slot from ever being DECODED — the frame it used to
            # hold is gone, and whatever the allocator did with those bytes is
            # not a coroutine frame.
            if reader.byte(done_ptr + slot * desc["bool_elem"]):
                continue
            elem = tasks_ptr + slot * desc["task_elem"]
            if not reader.byte(elem + desc["task_present"]):
                continue
            data = reader.word(elem + desc["task_data"])
            vtable = reader.word(elem + desc["task_vtable"])
            if not data:
                continue
            out.append({
                "group": group_number,
                "group_addr": group,
                "slot": slot,
                "generation": reader.word(gen_ptr + slot * word),
                "remaining": reader.word(rem_ptr + slot * word),
                "active": bool(reader.byte(active_ptr
                                           + slot * desc["bool_elem"])),
                "workers": workers,
                "frame": data,
                "index": vtables.get(vtable, -1),
            })
        group = reader.word(group + desc["off_bt_next"])
    return out


def _describe(task, table, reader):
    stack = _walk(table, reader, task["index"], task["frame"])
    lines = []
    for frame, line, base, note in reversed(stack):
        if frame is None:
            lines.append(f"    <{note}>")
            continue
        where = f"{frame['file']}:{line}" if line else frame["file"]
        suffix = f"   ({note})" if note else ""
        lines.append(f"    at {where} in {frame['name']}"
                     f"   [frame {base:#x}]{suffix}")
    return lines


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def _run(debugger, result, full):
    try:
        target, process = _target(debugger)
        table = _load_table(target, process)
        tasks = _tasks(target, process, table)
    except SawError as e:
        result.SetError(str(e))
        return
    if not table["frames"]:
        result.AppendMessage("this binary has no coroutine frames")
        return
    if not tasks:
        result.AppendMessage("no live tasks")
        return
    reader = _Reader(process, table["word_bits"] // 8)
    result.AppendMessage(f"{len(tasks)} live task(s)")
    for task in tasks:
        engine = "mt" if task["workers"] >= 2 else "st"
        state = "running" if task["active"] else _wake_text(task["remaining"])
        result.AppendMessage(
            f"  task group {task['group']} slot {task['slot']} "
            f"gen {task['generation']} [{engine}] {state}")
        if full:
            try:
                for line in _describe(task, table, reader):
                    result.AppendMessage(line)
            except SawError as e:
                result.AppendMessage(f"    <{e}>")


def saw_tasks(debugger, command, result, internal_dict):
    """One line per live task: which group and slot it holds and why it is not
    running."""
    _run(debugger, result, full=False)


def saw_bt(debugger, command, result, internal_dict):
    """Every live task's logical backtrace, innermost frame first."""
    _run(debugger, result, full=True)


def saw_table(debugger, command, result, internal_dict):
    """The backtrace table this binary carries, decoded.

    Needs no process — the table is read-only data — so it is what to reach for
    when `saw bt` says something surprising: it shows what the compiler recorded
    about every frame, which is the other half of any disagreement.
    """
    try:
        target, process = _target(debugger, need_process=False)
        table = _load_table(target, process)
    except SawError as e:
        result.SetError(str(e))
        return
    result.AppendMessage(
        f"backtrace table v{table['version']}: {len(table['frames'])} frame(s), "
        f"{table['bytes']} bytes, {table['word_bits']}-bit")
    for index, frame in enumerate(table["frames"]):
        result.AppendMessage(
            f"  [{index}] {frame['name']}  ({frame['file']}, "
            f"__state at +{frame['state_field']})")
        for state, entry in enumerate(frame["states"]):
            if entry["child"] >= 0:
                child = table["frames"][entry["child"]]["name"]
                result.AppendMessage(
                    f"      state {state}: line {entry['line']}, inside "
                    f"{child} at +{entry['child_offset']}")
            elif entry["line"]:
                result.AppendMessage(
                    f"      state {state}: parked at line {entry['line']}")
    # The one thing the live walk needs that is not IN the table: the vtable
    # map. Reported here so a mismatch is visible before anything runs. With no
    # process the pointers are unrelocated, so this only says the array is
    # THERE and the right length.
    if not _symbol_present(target, VTABLES_SYMBOL):
        result.AppendMessage(f"  WARNING: no `{VTABLES_SYMBOL}` — `saw bt` "
                             f"cannot identify a task's frame type")
    else:
        resolved = len(_vtable_index(target, (_Reader(process,
                                                      table["word_bits"] // 8)
                                              if process else None), table))
        result.AppendMessage(
            f"  frame vtable map: {VTABLES_SYMBOL}"
            + (f", {resolved} of {len(table['frames'])} resolved"
               if process else " (unrelocated — no process)"))
    if table["exec"] is None:
        result.AppendMessage("  no executor in this binary — no tasks to find")
    else:
        result.AppendMessage(
            f"  task list head: {table['exec']['head_symbol']}")


def __lldb_init_module(debugger, internal_dict):
    # NOTE: no apostrophes in these help strings. lldb splits a command line on
    # quotes before it parses options, so a `-h 'the program's tasks'` closes
    # early and the rest of the line becomes garbage command-path components —
    # which registers the command under a name nobody can type, with an error
    # that names a word out of the help text.
    module = __name__
    debugger.HandleCommand(
        "command container add -h \"Saw language support (design 158)\" saw")
    debugger.HandleCommand(
        f"command script add -f {module}.saw_tasks "
        f"-h \"list the live cooperative tasks\" saw tasks")
    debugger.HandleCommand(
        f"command script add -f {module}.saw_bt "
        f"-h \"logical backtrace of every live cooperative task\" saw bt")
    debugger.HandleCommand(
        f"command script add -f {module}.saw_table "
        f"-h \"decode the in-binary backtrace table\" saw table")
    print("saw: `saw tasks`, `saw bt` and `saw table` are available")
