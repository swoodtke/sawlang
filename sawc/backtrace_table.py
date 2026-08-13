"""The in-binary logical-backtrace table (`__saw_bt_table`, design 158).

A suspended Saw task is ONE flat allocation: the root coroutine frame, with
every suspending callee's frame embedded BY VALUE at a compile-time-known
offset, each frame carrying a `__state` word naming its resume point. So the
logical stack of a parked task is a pure STATIC table walk — no pointer
chasing, no unwinder:

    root frame -> read `__state`
                  -> "parked at line N"          (leaf: print and stop)
                  -> "inside child C at offset K" (print the call line, recurse)

The compiler already has both halves. The embedding tree and each child's
single live state come from the coro transform (`coro_frame_info.sub_states`);
the per-state source line comes from the same pass (`state_lines`); the byte
offsets come from LLVM, which is the layout authority. This module joins them
into one compact read-only blob and hands it to codegen, which links it under
the symbol `__saw_bt_table`.

ONE encoding serves both consumers, which is the point of freezing it here:

  * the in-process walker (`std/taskgroup.saw`, design 158 unit 3) reads it at
    the link-time symbol through the `__saw_bt_table()` intrinsic, and prints a
    task dump on the alloc-free path — hosted and freestanding;
  * `tools/lldb_saw.py` reads the same bytes out of a stopped target.

It is ALWAYS ON. A table behind a flag is a table you do not have when a
program panics in a way you did not plan for, which is the whole reason the
in-process dump exists. The cost is bounded and small: a frame record is 24
bytes, a state entry is 12, and names are shared in one string table.

## Layout

All integers little-endian. Offsets are from the start of the blob.

    HEADER (32 bytes)
      0  u32  magic 'SAWB' (0x42574153)
      4  u16  version (1)
      6  u16  word_bits (64 / 32) — the target's pointer width
      8  u32  frame_count
     12  u32  frames_off
     16  u32  states_off
     20  u32  strtab_off
     24  u32  strtab_len
     28  u32  exec_off   — the runtime descriptor, 0 when absent

    FRAME RECORD (24 bytes)
      0  u32  sym_off      -> "__Frame_run"  (the LLVM type identity)
      4  u32  name_off     -> "run"          (what a backtrace prints)
      8  u32  file_off     -> "worker.saw"
     12  u32  state_first  — index of this frame's first state entry
     16  u32  state_count
     20  u32  state_field  — byte offset of `__state` inside the frame

    STATE ENTRY (12 bytes)
      0  u32  line          — 0 when unknown
      4  u32  child_frame   — the live child's frame index PLUS ONE; 0 = this
                              state is a leaf park. Biased rather than -1 so a
                              32-bit walker can read the field into its own
                              `Int` — an all-ones sentinel does not fit a
                              signed 32-bit word, and the in-process walker is
                              the same Saw source on riscv32 as on x86-64.
      8  u32  child_offset  — byte offset of the live child sub-frame

    RUNTIME DESCRIPTOR (`exec_off`, 64 bytes, all u32) — what a DEBUGGER needs
    to find the tasks in the first place. The in-process walker does not read
    it (it reaches the group through ordinary Saw field access); lldb has no
    type information for Saw, so the compiler writes the handful of offsets
    down rather than have the script hard-code a layout that can drift.

      0  u32  head_sym_off  -> the LLVM symbol of the group-list head global
      4  u32  group_size
      8  u32  off_tasks     — `TaskGroup.tasks`   (Vector<Box<any Resumable>?>)
     12  u32  off_done      — `TaskGroup.done`    (Vector<Bool>)
     16  u32  off_gen       — `TaskGroup.gen`     (Vector<Int>)
     20  u32  off_remaining — `TaskGroup.remaining`
     24  u32  off_active    — `TaskGroup.active`
     28  u32  off_workers   — `TaskGroup.workers`
     32  u32  off_bt_next   — `TaskGroup.bt_next` (the diagnostics list link)
     36  u32  vec_ptr_off   — byte offset of a Vector's element pointer
     40  u32  vec_len_off   — byte offset of a Vector's length
     44  u32  task_elem     — sizeof(Box<any Resumable>?)
     48  u32  task_present  — offset of the Optional's present flag
     52  u32  task_data     — offset of the box's data word
     56  u32  task_vtable   — offset of the box's vtable word
     60  u32  bool_elem     — sizeof(Bool) as a Vector element

Reporting-adjacent, like `frame_layout.py`: nothing here influences code
generation beyond the bytes it returns.
"""

import struct

FRAME_PREFIX = "__Frame_"
MAGIC = 0x42574153          # 'SAWB' little-endian
VERSION = 1
HEADER_SIZE = 32
FRAME_REC_SIZE = 24
STATE_REC_SIZE = 12
EXEC_REC_SIZE = 64

# The name of the intrusive list every TaskGroup joins for diagnostics
# (std/taskgroup.saw). Statics are emitted as `saw.static.<name>$m$<module>`,
# so the descriptor records the symbol the compile actually produced rather
# than a spelling the debugger would have to guess.
HEAD_STATIC = "__saw_bt_head"

_TASKGROUP = "TaskGroup"
_TG_FIELDS = ("tasks", "done", "gen", "remaining", "active", "workers",
              "bt_next")


def _align_up(n, a):
    return n if a <= 1 else ((n + a - 1) // a) * a


def _elem_offsets(codegen, llvm_type):
    """Byte offset of each element of an LLVM struct type.

    The same C-layout walk `frame_layout.py` uses and cross-checks against
    `get_abi_size`, so the two reports cannot disagree about a frame.
    """
    offsets = []
    offset = 0
    for ety in llvm_type.elements:
        align = codegen._abi_align(ety) or 1
        offset = _align_up(offset, align)
        offsets.append(offset)
        offset += codegen._abi_size(ety)
    return offsets


class _StrTab:
    """The blob's string table: NUL-terminated, deduplicated, offset 0 empty."""

    def __init__(self):
        self.blob = bytearray(b"\0")
        self._seen = {"": 0}

    def add(self, text):
        text = text or ""
        hit = self._seen.get(text)
        if hit is not None:
            return hit
        off = len(self.blob)
        self.blob += text.encode("utf-8") + b"\0"
        self._seen[text] = off
        return off


def _basename(path):
    if not path:
        return ""
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _collect_frames(codegen, program):
    """Every monomorphized frame, in the table's order.

    The order is the `bt_index` the coro transform assigned (frame name sorted),
    because that index is baked into each frame's `bt_desc` body — the table
    and the vtables have to agree, so the transform is the authority and this
    pass follows it.
    """
    entries = []
    for struct_node in getattr(program, "structs", []):
        ci = getattr(struct_node, "coro_frame_info", None)
        if ci is None or ci.get("bt_index") is None:
            continue
        registered = codegen.struct_types.get(struct_node.name)
        if registered is None:
            # A frame the transform built but codegen never registered is not
            # something to guess a layout for — leave it out; the walker reports
            # the index as unknown rather than decoding garbage.
            continue
        entries.append((ci["bt_index"], struct_node, ci, registered))
    entries.sort(key=lambda e: e[0])
    return entries


def _exec_descriptor(codegen, strtab):
    """The debugger's map to the live-task list, or None when the program has
    no executor in it (nothing imported `TaskGroup`, so there are no tasks)."""
    registered = codegen.struct_types.get(_TASKGROUP)
    if registered is None:
        return None
    tg_type, tg_fields = registered
    if not all(f in tg_fields for f in _TG_FIELDS):
        return None
    offsets = _elem_offsets(codegen, tg_type)
    idx = {name: i for i, name in enumerate(tg_fields)}

    head_sym = ""
    for gv in codegen.module.global_values:
        name = getattr(gv, "name", "")
        if name.startswith(f"saw.static.{HEAD_STATIC}"):
            head_sym = name
            break

    # A Vector is `{ {i1 present, T* data}, len, capacity }`; the element
    # pointer lives inside that Optional, so the walk is two levels deep.
    vec_type = tg_type.elements[idx["tasks"]]
    vec_off = _elem_offsets(codegen, vec_type)
    opt_ptr_type = vec_type.elements[0]
    vec_ptr_off = vec_off[0] + _elem_offsets(codegen, opt_ptr_type)[1]
    vec_len_off = vec_off[1]

    # The element: `Box<any Resumable>?` = `{ i1 present, { i8* data, i8* vt } }`.
    elem_type = opt_ptr_type.elements[1].pointee
    elem_off = _elem_offsets(codegen, elem_type)
    box_type = elem_type.elements[1]
    box_off = _elem_offsets(codegen, box_type)

    bool_vec = tg_type.elements[idx["done"]]
    bool_elem = codegen._abi_size(
        bool_vec.elements[0].elements[1].pointee)

    return struct.pack(
        "<16I",
        strtab.add(head_sym),
        codegen._abi_size(tg_type),
        offsets[idx["tasks"]],
        offsets[idx["done"]],
        offsets[idx["gen"]],
        offsets[idx["remaining"]],
        offsets[idx["active"]],
        offsets[idx["workers"]],
        offsets[idx["bt_next"]],
        vec_ptr_off,
        vec_len_off,
        codegen._abi_size(elem_type),
        elem_off[0],
        elem_off[1] + box_off[0],
        elem_off[1] + box_off[1],
        bool_elem,
    )


def build_table(codegen, program):
    """Encode the whole table. Always returns bytes — a program with no
    coroutine frames gets a well-formed header with `frame_count == 0`, so the
    symbol exists in every binary and neither consumer needs a special case."""
    strtab = _StrTab()
    frames = _collect_frames(codegen, program)

    frame_recs = bytearray()
    state_recs = bytearray()
    for _index, struct_node, ci, (llvm_type, field_order) in frames:
        offsets = _elem_offsets(codegen, llvm_type)
        by_name = {name: offsets[i] for i, name in enumerate(field_order)}
        state_count = int(ci.get("states") or 0)
        state_lines = ci.get("state_lines") or {}
        # `__subN` -> (child frame index, byte offset), keyed by the ONE state
        # in which that child's storage is live.
        child_at = {}
        for sub, live_state in (ci.get("sub_states") or {}).items():
            if live_state is None or sub not in by_name:
                continue
            callee = getattr(llvm_type.elements[field_order.index(sub)],
                             "name", None)
            child_at[live_state] = (callee, by_name[sub])

        first = len(state_recs) // STATE_REC_SIZE
        for state in range(state_count):
            callee_off = child_at.get(state)
            if callee_off is None:
                child_index, child_offset = -1, 0
            else:
                callee, child_offset = callee_off
                child_index = _index_of(frames, callee)
            if child_index < 0:
                child_index, child_offset = -1, 0
            state_recs += struct.pack("<3I",
                                      int(state_lines.get(state) or 0),
                                      child_index + 1, child_offset)
        frame_recs += struct.pack(
            "<6I",
            strtab.add(struct_node.name),
            strtab.add(ci.get("display_name") or struct_node.name),
            strtab.add(_basename(ci.get("source_file") or "")),
            first, state_count,
            by_name.get("__state", 0))

    exec_rec = _exec_descriptor(codegen, strtab)

    frames_off = HEADER_SIZE
    states_off = frames_off + len(frame_recs)
    exec_off = states_off + len(state_recs) if exec_rec else 0
    strtab_off = (exec_off + EXEC_REC_SIZE) if exec_rec else \
        (states_off + len(state_recs))
    header = struct.pack("<IHHIIIIII", MAGIC, VERSION,
                         codegen._abi_size(codegen.int_type) * 8,
                         len(frames), frames_off, states_off,
                         strtab_off, len(strtab.blob), exec_off)
    return bytes(header + frame_recs + state_recs
                 + (exec_rec or b"") + bytes(strtab.blob))


def _index_of(frames, frame_type_name):
    for index, struct_node, _ci, _reg in frames:
        if struct_node.name == frame_type_name:
            return index
    return -1


# --------------------------------------------------------------------------- #
# Decoding — used by `--emit-bt-table` and by the lldb script (which imports
# this module when it can see the source tree, and carries its own copy of the
# format otherwise). Keeping the reader beside the writer is what stops the two
# from drifting.
# --------------------------------------------------------------------------- #

def decode(blob):
    """Decode a table blob into plain dicts. Raises ValueError on a bad magic
    or version — a wrong answer about where a program is parked is worse than
    no answer."""
    if len(blob) < HEADER_SIZE:
        raise ValueError("backtrace table is shorter than its header")
    (magic, version, word_bits, frame_count, frames_off, states_off,
     strtab_off, strtab_len, exec_off) = struct.unpack_from(
        "<IHHIIIIII", blob, 0)
    if magic != MAGIC:
        raise ValueError(f"not a Saw backtrace table (magic {magic:#x})")
    if version != VERSION:
        raise ValueError(f"backtrace table version {version} is not "
                         f"{VERSION}; rebuild with this compiler")

    def string_at(off):
        if off == 0:
            return ""
        end = blob.index(b"\0", strtab_off + off)
        return blob[strtab_off + off:end].decode("utf-8", "replace")

    frames = []
    for i in range(frame_count):
        (sym, name, file_off, first, count, state_field) = struct.unpack_from(
            "<6I", blob, frames_off + i * FRAME_REC_SIZE)
        states = []
        for s in range(count):
            line, child, child_off = struct.unpack_from(
                "<3I", blob, states_off + (first + s) * STATE_REC_SIZE)
            states.append({"line": line, "child": child - 1,
                           "child_offset": child_off})
        frames.append({"symbol": string_at(sym), "name": string_at(name),
                       "file": string_at(file_off),
                       "state_field": state_field, "states": states})

    exec_desc = None
    if exec_off:
        vals = struct.unpack_from("<16I", blob, exec_off)
        keys = ("head_symbol", "group_size", "off_tasks", "off_done",
                "off_gen", "off_remaining", "off_active", "off_workers",
                "off_bt_next", "vec_ptr_off", "vec_len_off", "task_elem",
                "task_present", "task_data", "task_vtable", "bool_elem")
        exec_desc = dict(zip(keys, vals))
        exec_desc["head_symbol"] = string_at(vals[0])

    return {"version": version, "word_bits": word_bits, "bytes": len(blob),
            "strtab_bytes": strtab_len, "frames": frames, "exec": exec_desc}


def render(blob):
    import json
    return json.dumps(decode(blob), indent=2, sort_keys=True) + "\n"
