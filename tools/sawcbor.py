#!/usr/bin/env python3
"""The Python half of the design-169 wire contract.

`sawc/std/CBOR.md` is the frozen profile. This tool holds the OTHER
implementation of it, over the `cbor2` library, so the golden vectors under
`tests/cbor_vectors/` are checked against two independent readers rather than
against whichever one was written first.

  tools/sawcbor.py gen              rewrite the golden vectors from the case table
  tools/sawcbor.py verify           check every vector round-trips byte-identically
  tools/sawcbor.py diag <file>      RFC 8949 diagnostic notation for a blob

`verify` is the gate. For each accepted vector it checks, independently:
  * the blob is in the deterministic profile (shortest form, definite lengths,
    sorted map keys, no floats/tags/undefined, one top-level item);
  * `cbor2.loads` reads it and re-encodes to the SAME bytes;
  * the `.json` sidecar describes that same value.
For each rejected vector it checks the profile scanner refuses it, with the
fault the sidecar names.
"""

import argparse
import base64
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VECTOR_DIR = os.path.join(REPO, "tests", "cbor_vectors")

try:
    import cbor2
except ImportError:  # pragma: no cover - the gate reports this itself
    cbor2 = None


# --------------------------------------------------------------------------
# The profile scanner. Deliberately hand-written rather than delegated to
# cbor2: cbor2 ACCEPTS non-canonical CBOR, and "the bytes are the value" is
# exactly the property the vectors exist to police.
# --------------------------------------------------------------------------

class ProfileError(Exception):
    def __init__(self, fault, offset, detail=""):
        super().__init__(f"{fault} at byte {offset}{': ' + detail if detail else ''}")
        self.fault = fault
        self.offset = offset


MAJOR_UNSIGNED = 0
MAJOR_NEGATIVE = 1
MAJOR_BYTES = 2
MAJOR_TEXT = 3
MAJOR_ARRAY = 4
MAJOR_MAP = 5
MAJOR_TAG = 6
MAJOR_SIMPLE = 7


def _shortest_argument_ok(value, info):
    """Whether `info` is the shortest additional-info spelling for `value`."""
    if value < 24:
        return info == value
    if value < 0x100:
        return info == 24
    if value < 0x10000:
        return info == 25
    if value < 0x100000000:
        return info == 26
    return info == 27


class _Scanner:
    def __init__(self, data, max_depth=64, max_items=100000):
        self.data = data
        self.pos = 0
        self.max_depth = max_depth
        self.max_items = max_items
        self.items = 0

    def _need(self, n):
        if self.pos + n > len(self.data):
            raise ProfileError("Truncated", self.pos)

    def _argument(self, info):
        """The argument of the head just read, checked for shortest form."""
        start = self.pos - 1
        if info < 24:
            return info
        if info == 24:
            self._need(1)
            v = self.data[self.pos]
            self.pos += 1
        elif info == 25:
            self._need(2)
            v = int.from_bytes(self.data[self.pos:self.pos + 2], "big")
            self.pos += 2
        elif info == 26:
            self._need(4)
            v = int.from_bytes(self.data[self.pos:self.pos + 4], "big")
            self.pos += 4
        elif info == 27:
            self._need(8)
            v = int.from_bytes(self.data[self.pos:self.pos + 8], "big")
            self.pos += 8
        elif info == 31:
            raise ProfileError("Unsupported", start,
                               "indefinite length is outside the profile")
        else:
            raise ProfileError("Malformed", start,
                               f"reserved additional info {info}")
        if not _shortest_argument_ok(v, info):
            raise ProfileError("NotCanonical", start,
                               f"{v} is not in shortest form")
        return v

    def item(self, depth=0):
        """Scan one item, returning (value, encoded_slice_start)."""
        if depth > self.max_depth:
            raise ProfileError("TooDeep", self.pos)
        self.items += 1
        if self.items > self.max_items:
            raise ProfileError("TooManyItems", self.pos)
        self._need(1)
        start = self.pos
        head = self.data[self.pos]
        self.pos += 1
        major = head >> 5
        info = head & 0x1f

        if major == MAJOR_UNSIGNED:
            return self._argument(info), start
        if major == MAJOR_NEGATIVE:
            return -1 - self._argument(info), start
        if major in (MAJOR_BYTES, MAJOR_TEXT):
            n = self._argument(info)
            self._need(n)
            raw = self.data[self.pos:self.pos + n]
            self.pos += n
            if major == MAJOR_TEXT:
                try:
                    return raw.decode("utf-8"), start
                except UnicodeDecodeError:
                    raise ProfileError("Malformed", start, "text is not UTF-8")
            return raw, start
        if major == MAJOR_ARRAY:
            n = self._argument(info)
            out = []
            for _ in range(n):
                v, _s = self.item(depth + 1)
                out.append(v)
            return out, start
        if major == MAJOR_MAP:
            n = self._argument(info)
            out = {}
            prev_key_bytes = None
            for _ in range(n):
                kstart = self.pos
                k, _s = self.item(depth + 1)
                kbytes = self.data[kstart:self.pos]
                if prev_key_bytes is not None:
                    if kbytes == prev_key_bytes:
                        raise ProfileError("Malformed", kstart, "duplicate map key")
                    if kbytes < prev_key_bytes:
                        raise ProfileError("NotCanonical", kstart,
                                           "map keys are not in canonical order")
                prev_key_bytes = kbytes
                v, _s = self.item(depth + 1)
                out[k if not isinstance(k, bytes) else k.hex()] = v
            return out, start
        if major == MAJOR_TAG:
            raise ProfileError("Unsupported", start, "tags are not in v1")
        # major 7
        if info == 20:
            return False, start
        if info == 21:
            return True, start
        if info == 22:
            return None, start
        if info == 23:
            raise ProfileError("Unsupported", start, "`undefined` is not in the profile")
        if info in (25, 26, 27):
            raise ProfileError("Unsupported", start, "floats are not in v1")
        raise ProfileError("Unsupported", start, f"simple value {info}")


def scan(data, **kw):
    """Decode `data` under the profile. Raises ProfileError on any violation."""
    s = _Scanner(data, **kw)
    value, _ = s.item()
    if s.pos != len(data):
        raise ProfileError("TrailingBytes", s.pos)
    return value


# --------------------------------------------------------------------------
# Canonical encoding
# --------------------------------------------------------------------------

def _head(major, value):
    if value < 24:
        return bytes([(major << 5) | value])
    if value < 0x100:
        return bytes([(major << 5) | 24, value])
    if value < 0x10000:
        return bytes([(major << 5) | 25]) + value.to_bytes(2, "big")
    if value < 0x100000000:
        return bytes([(major << 5) | 26]) + value.to_bytes(4, "big")
    if value < 0x10000000000000000:
        return bytes([(major << 5) | 27]) + value.to_bytes(8, "big")
    raise ValueError(f"{value} does not fit a CBOR argument")


def encode(value):
    """Encode `value` in the deterministic profile."""
    if value is None:
        return b"\xf6"
    if value is True:
        return b"\xf5"
    if value is False:
        return b"\xf4"
    if isinstance(value, int):
        if value >= 0:
            return _head(MAJOR_UNSIGNED, value)
        return _head(MAJOR_NEGATIVE, -1 - value)
    if isinstance(value, bytes):
        return _head(MAJOR_BYTES, len(value)) + value
    if isinstance(value, str):
        raw = value.encode("utf-8")
        return _head(MAJOR_TEXT, len(raw)) + raw
    if isinstance(value, (list, tuple)):
        out = _head(MAJOR_ARRAY, len(value))
        for item in value:
            out += encode(item)
        return out
    if isinstance(value, dict):
        pairs = [(encode(k), encode(v)) for k, v in value.items()]
        pairs.sort(key=lambda kv: kv[0])
        out = _head(MAJOR_MAP, len(pairs))
        for k, v in pairs:
            out += k + v
        return out
    if isinstance(value, float):
        raise ValueError("floats are not in the v1 profile")
    raise ValueError(f"no profile encoding for {type(value).__name__}")


# --------------------------------------------------------------------------
# Diagnostic notation (RFC 8949 §8) — the free text rendering for debugging
# --------------------------------------------------------------------------

def diagnostic(value):
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, bytes):
        return "h'" + value.hex() + "'"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(diagnostic(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{diagnostic(k)}: {diagnostic(v)}"
                               for k, v in value.items()) + "}"
    raise ValueError(f"no diagnostic form for {type(value).__name__}")


# --------------------------------------------------------------------------
# The golden case table. One entry per vector; `gen` writes them out and
# `verify` reads them back. Keep the names stable — they are what the Saw-side
# harness names too.
# --------------------------------------------------------------------------

ACCEPT_CASES = [
    ("uint_zero", 0),
    ("uint_inline_max", 23),
    ("uint_one_byte", 24),
    ("uint_255", 255),
    ("uint_256", 256),
    ("uint_65535", 65535),
    ("uint_65536", 65536),
    ("uint_u32_max", 4294967295),
    ("uint_u32_max_plus", 4294967296),
    ("nint_minus_one", -1),
    ("nint_minus_24", -24),
    ("nint_minus_25", -25),
    ("nint_minus_256", -256),
    ("nint_minus_65537", -65537),
    ("bool_false", False),
    ("bool_true", True),
    ("null", None),
    ("text_empty", ""),
    ("text_ascii", "api"),
    ("text_utf8", "café — \U0001f600"),
    ("bytes_empty", b""),
    ("bytes_short", bytes([0xde, 0xad, 0xbe, 0xef])),
    ("array_empty", []),
    ("array_ints", [1, 2, 3]),
    ("array_nested", [[1], [2, [3]]]),
    ("array_mixed", [1, "two", True, None]),
    ("map_empty", {}),
    ("map_sorted_text", {"a": 1, "b": 2}),
    ("map_int_keys", {1: "one", 2: "two"}),
    ("struct_endpoint", [443, True, "api"]),
    ("struct_nested", ["saw", [1, 2, 3], None]),
    ("lock_entry", ["toml", "0.1.0", "path", "libs/toml", ""]),
]

# Blobs that must be REFUSED, each with the fault the profile names.
REJECT_CASES = [
    ("truncated_head", bytes([0x18]), "Truncated"),
    ("truncated_text", bytes([0x63, 0x61]), "Truncated"),
    ("truncated_array", bytes([0x82, 0x01]), "Truncated"),
    ("nonshortest_uint8", bytes([0x18, 0x17]), "NotCanonical"),
    ("nonshortest_uint16", bytes([0x19, 0x00, 0x18]), "NotCanonical"),
    ("nonshortest_uint32", bytes([0x1a, 0x00, 0x00, 0x01, 0x00]), "NotCanonical"),
    ("nonshortest_nint", bytes([0x38, 0x17]), "NotCanonical"),
    ("indefinite_text", bytes([0x7f, 0x61, 0x61, 0xff]), "Unsupported"),
    ("indefinite_array", bytes([0x9f, 0x01, 0xff]), "Unsupported"),
    ("indefinite_map", bytes([0xbf, 0x61, 0x61, 0x01, 0xff]), "Unsupported"),
    ("float64", bytes([0xfb, 0x40, 0x09, 0x21, 0xfb, 0x54, 0x44, 0x2d, 0x18]),
     "Unsupported"),
    ("float16", bytes([0xf9, 0x3c, 0x00]), "Unsupported"),
    ("tagged", bytes([0xc0, 0x61, 0x61]), "Unsupported"),
    # A tag whose argument is multi-byte. `tagged` above only covers an inline
    # argument, so a reader that parses the argument before judging the major
    # reports the ARGUMENT's shape (here: not shortest-form) and passes the
    # vectors anyway. Rule 5 admits no exceptions, so the fault is the tag's.
    ("tagged_multibyte", bytes([0xd8, 0x05]), "Unsupported"),
    ("undefined", bytes([0xf7]), "Unsupported"),
    ("map_unsorted", bytes([0xa2, 0x61, 0x62, 0x01, 0x61, 0x61, 0x02]),
     "NotCanonical"),
    ("map_duplicate_key", bytes([0xa2, 0x61, 0x61, 0x01, 0x61, 0x61, 0x02]),
     "Malformed"),
    ("trailing_bytes", bytes([0x01, 0x02]), "TrailingBytes"),
    ("bad_utf8", bytes([0x62, 0xff, 0xfe]), "Malformed"),
    ("reserved_info", bytes([0x1c]), "Malformed"),
]


def _sidecar(value):
    """A JSON-describable form of a CBOR value (bytes become base64)."""
    if isinstance(value, bytes):
        return {"__bytes__": base64.b64encode(value).decode("ascii")}
    if isinstance(value, list):
        return [_sidecar(v) for v in value]
    if isinstance(value, dict):
        return {"__map__": [[_sidecar(k), _sidecar(v)] for k, v in value.items()]}
    return value


def _unsidecar(node):
    if isinstance(node, dict):
        if "__bytes__" in node:
            return base64.b64decode(node["__bytes__"])
        if "__map__" in node:
            return {_unsidecar(k): _unsidecar(v) for k, v in node["__map__"]}
    if isinstance(node, list):
        return [_unsidecar(v) for v in node]
    return node


def cmd_gen(_args):
    accept_dir = os.path.join(VECTOR_DIR, "accept")
    reject_dir = os.path.join(VECTOR_DIR, "reject")
    os.makedirs(accept_dir, exist_ok=True)
    os.makedirs(reject_dir, exist_ok=True)
    for name, value in ACCEPT_CASES:
        blob = encode(value)
        with open(os.path.join(accept_dir, name + ".cbor"), "wb") as f:
            f.write(blob)
        with open(os.path.join(accept_dir, name + ".json"), "w") as f:
            json.dump({"name": name, "value": _sidecar(value),
                       "hex": blob.hex(), "diagnostic": diagnostic(value)},
                      f, indent=2, sort_keys=True)
            f.write("\n")
    for name, blob, fault in REJECT_CASES:
        with open(os.path.join(reject_dir, name + ".cbor"), "wb") as f:
            f.write(blob)
        with open(os.path.join(reject_dir, name + ".json"), "w") as f:
            json.dump({"name": name, "fault": fault, "hex": blob.hex()},
                      f, indent=2, sort_keys=True)
            f.write("\n")
    print(f"sawcbor: wrote {len(ACCEPT_CASES)} accept + {len(REJECT_CASES)} "
          f"reject vector(s) to {os.path.relpath(VECTOR_DIR, REPO)}")
    return 0


def cmd_verify(_args):
    failures = []
    accept_dir = os.path.join(VECTOR_DIR, "accept")
    reject_dir = os.path.join(VECTOR_DIR, "reject")
    if not os.path.isdir(accept_dir):
        print("sawcbor: no vectors — run `tools/sawcbor.py gen` first",
              file=sys.stderr)
        return 1

    n_accept = 0
    for fname in sorted(os.listdir(accept_dir)):
        if not fname.endswith(".cbor"):
            continue
        n_accept += 1
        name = fname[:-5]
        path = os.path.join(accept_dir, fname)
        with open(path, "rb") as f:
            blob = f.read()
        with open(os.path.join(accept_dir, name + ".json")) as f:
            side = json.load(f)
        expected = _unsidecar(side["value"])
        # 1. the profile scanner accepts it and reads the sidecar's value
        try:
            got = scan(blob)
        except ProfileError as err:
            failures.append(f"{name}: profile scan refused it ({err})")
            continue
        want = expected
        if isinstance(want, dict):
            want = {(k.hex() if isinstance(k, bytes) else k): v
                    for k, v in want.items()}
        if got != want:
            failures.append(f"{name}: scanned {got!r}, sidecar says {want!r}")
        # 2. re-encoding the sidecar value reproduces the bytes exactly
        if encode(expected) != blob:
            failures.append(f"{name}: re-encode is not byte-identical")
        if side.get("hex") != blob.hex():
            failures.append(f"{name}: sidecar hex does not match the blob")
        # 3. the independent cbor2 reader agrees, and its re-encode matches
        if cbor2 is not None:
            try:
                via = cbor2.loads(blob)
            except Exception as err:  # noqa: BLE001 - report whatever it raised
                failures.append(f"{name}: cbor2 refused it ({err})")
                continue
            if cbor2.dumps(via, canonical=True) != blob:
                failures.append(f"{name}: cbor2 canonical re-encode differs")

    n_reject = 0
    for fname in sorted(os.listdir(reject_dir)):
        if not fname.endswith(".cbor"):
            continue
        n_reject += 1
        name = fname[:-5]
        with open(os.path.join(reject_dir, fname), "rb") as f:
            blob = f.read()
        with open(os.path.join(reject_dir, name + ".json")) as f:
            side = json.load(f)
        try:
            value = scan(blob)
        except ProfileError as err:
            if err.fault != side["fault"]:
                failures.append(
                    f"{name}: refused as {err.fault}, expected {side['fault']}")
            continue
        failures.append(f"{name}: ACCEPTED {value!r} but must be refused "
                        f"({side['fault']})")

    for f in failures:
        print(f"sawcbor: FAIL {f}", file=sys.stderr)
    if failures:
        print(f"sawcbor: {len(failures)} failure(s)", file=sys.stderr)
        return 1
    extra = "" if cbor2 is not None else " (cbor2 absent — cross-check skipped)"
    print(f"sawcbor: OK — {n_accept} accept + {n_reject} reject vector(s) "
          f"round-trip byte-identically{extra}")
    return 0


def cmd_diag(args):
    with open(args.file, "rb") as f:
        blob = f.read()
    print(diagnostic(scan(blob)))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gen", help="rewrite the golden vectors")
    sub.add_parser("verify", help="check every vector round-trips")
    d = sub.add_parser("diag", help="diagnostic notation for a blob")
    d.add_argument("file")
    args = p.parse_args(argv)
    return {"gen": cmd_gen, "verify": cmd_verify, "diag": cmd_diag}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
