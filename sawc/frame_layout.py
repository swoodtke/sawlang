"""Coroutine frame layout report (`--emit-frame-layout`, design 163).

Every suspending function becomes a `__Frame_<f>` struct (coro_transform's
`_FrameBuilder.prepare`): its params, its across-suspend locals, one `__subN`
field per nested suspending call site holding the CALLEE's whole frame by
value, and the scheduler words. The flat-frame model (design 44) sizes a frame
by the SUM of every embedded child, so a function with several suspending call
sites pays for all of them at once and the cost compounds down the call tree.

This module reports what that actually costs: per monomorphized frame, the
total ABI size and alignment, each field's offset/size, and for each embedded
child the callee frame it holds and the single resume state in which it is
live. `tools/framesizes.py` sweeps a corpus with it and computes the
high-water-mark hypothetical.

Reporting only — nothing here influences code generation.
"""

import json
import os

FRAME_PREFIX = "__Frame_"


def _align_up(n, a):
    return n if a <= 1 else ((n + a - 1) // a) * a


def _elem_name(llvm_type):
    """The identified-struct name of an LLVM type, or None."""
    return getattr(llvm_type, "name", None)


def collect_frame_layouts(codegen, program):
    """Build the frame-layout report for a compiled program.

    `codegen.struct_types` maps a struct IDENTITY to `(llvm_type, field_order)`
    — the authority on layout, since it is the type LLVM was handed. The
    state-machine facts (state count, per-child live state) ride on the frame
    Struct AST node as `coro_frame_info`, stamped by the transform.
    """
    info_by_name = {}
    for struct in getattr(program, "structs", []):
        ci = getattr(struct, "coro_frame_info", None)
        if ci is not None:
            info_by_name[struct.name] = ci

    frames = {}
    for identity, (llvm_type, field_order) in codegen.struct_types.items():
        if not identity.startswith(FRAME_PREFIX):
            continue
        elements = list(llvm_type.elements)
        if len(elements) != len(field_order):
            # Defensive: a frame whose registered body disagrees with its field
            # order is not something to guess about — report it and move on.
            continue
        ci = info_by_name.get(identity, {})
        sub_states = ci.get("sub_states", {})

        offset = 0
        max_align = 1
        fields = []
        for name, ety in zip(field_order, elements):
            size = codegen._abi_size(ety)
            align = codegen._abi_align(ety) or 1
            max_align = max(max_align, align)
            offset = _align_up(offset, align)
            callee = _elem_name(ety)
            is_sub = bool(callee and callee.startswith(FRAME_PREFIX))
            entry = {
                "name": name,
                "offset": offset,
                "size": size,
                "align": align,
                "kind": "sub" if is_sub else "own",
            }
            if is_sub:
                entry["callee"] = callee
                entry["live_state"] = sub_states.get(name)
            fields.append(entry)
            offset += size
        computed = _align_up(offset, max_align)
        actual = codegen._abi_size(llvm_type)

        subs = [f for f in fields if f["kind"] == "sub"]
        frames[identity] = {
            "size": actual,
            "align": codegen._abi_align(llvm_type) or 1,
            # Cross-check: our C-layout walk must reproduce LLVM's own size, or
            # the per-field offsets above are not to be trusted.
            "layout_agrees": computed == actual,
            "own_bytes": sum(f["size"] for f in fields if f["kind"] == "own"),
            "sub_bytes": sum(f["size"] for f in subs),
            "children": [f["callee"] for f in subs],
            "states": ci.get("states"),
            "is_spawn_root": ci.get("is_spawn_root", False),
            "is_method": ci.get("is_method", False),
            "source_file": ci.get("source_file", ""),
            # design 158: the backtrace-table facts ride the same stash, so the
            # report doubles as the human-readable view of what got encoded.
            # `state_lines` keys are ints; JSON has string keys, so render them
            # as strings here rather than letting json.dumps do it silently.
            "bt_index": ci.get("bt_index"),
            "display_name": ci.get("display_name", ""),
            "state_lines": {str(k): v
                            for k, v in (ci.get("state_lines") or {}).items()},
            "fields": fields,
        }
    return frames


def build_report(codegen, program, source_path):
    frames = collect_frame_layouts(codegen, program)
    return {
        "source": os.path.abspath(source_path),
        "triple": getattr(codegen, "triple", ""),
        "frames": frames,
    }


def render_report(report):
    return json.dumps(report, indent=2, sort_keys=True) + "\n"
