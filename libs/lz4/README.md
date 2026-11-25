# lz4

LZ4 block compression for `Data`. The codec is lz4 1.10.0, vendored under
`vendor/lz4/` and compiled by Blade; the Saw half is three functions and an
error type, with no `unsafe` in their signatures.

```saw-fragment
import lz4.*
import std.data.{Data}

let original = try! "an aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa input".to_data()
let packed = try! compress(&original)
let restored = try! decompress(&packed, size: original.len())
```

## API

| Function | Result |
|---|---|
| `compress(&Data) -> Result<Data, Lz4Error>` | One LZ4 block holding the input. An empty input gives a one-byte block. |
| `decompress(&Data, size: Int) -> Result<Data, Lz4Error>` | The block's bytes, which must be exactly `size` of them. |
| `decompress(&Data, max_size: Int) -> Result<Data, Lz4Error>` | The block's bytes, at most `max_size` of them. |

A block stores neither its decompressed length nor a checksum. Keep the length
beside the block and decompress with `size:`. An LZ4 block may end after any run
of literals, so a truncated or damaged block can be a valid, shorter one:
`max_size:` returns it as `Ok` with fewer bytes, and only `size:` reports
`SizeMismatch`. Use `max_size:` when the length is not known; the limit is what
stops a hostile block from expanding without bound.

`Lz4Error` conforms to `Error` and `Printable`:

| Case | Meaning |
|---|---|
| `InputTooLarge(size:)` | The input is longer than `MAX_INPUT_SIZE` (0x7E000000 bytes). |
| `InvalidLimit(value:)` | `max_size` (or `size`) is negative or does not fit in 32 bits. |
| `CompressFailed` | lz4 produced no output. Not reachable for an input within `MAX_INPUT_SIZE`. |
| `Malformed(code:)` | The block is corrupt, or its output exceeds the limit. lz4 reports both as one negative code. |
| `SizeMismatch(expected:got:)` | `decompress(size:)` decoded `got` bytes where the caller recorded `expected`. |
| `Alloc(e:)` | The scratch buffer or the result could not be allocated. |

Compression allocates lz4's 16 KiB state on the heap (`LZ4_sizeofState`,
passed to `LZ4_compress_fast_extState`), so it needs little stack: the Saw
function's frame is a few hundred bytes. Each call then copies through one
scratch buffer, allocating its worst-case size once and then the exact result.

## The C half

`Saw.toml` shows the `[native]` inputs Blade supports:

```toml
[native]
c-sources = ["vendor/lz4/lz4.c"]
include-dirs = ["vendor/lz4"]

[native.riscv32-unknown-none-elf]
defines = ["LZ4_FREESTANDING=1", ...]
```

The table is repeated for `aarch64-unknown-none-elf` and
`xtensa-esp-unknown-elf`, so the package builds for each bare-metal triple
sawc records.

Blade compiles `lz4.c` for each target a dependent package builds for, caches
the object by its flags, and links it into the program. The freestanding table
turns on lz4's `LZ4_FREESTANDING` mode, which requires the three memory
routines to be named by macro. Blade's `defines` take object-like macros only,
so they are aliases for the compiler's builtins (`LZ4_memcpy=__builtin_memcpy`);
a freestanding Saw object defines `memcpy`, `memmove` and `memset` weakly for
the builtins to fall back on. `LZ4_STATIC_LINKING_ONLY_DISABLE_MEMORY_ALLOCATION`
removes the streaming-context functions that call `malloc`; this package does
not use them.

`vendor/README.md` records the vendored version, its URL and hashes.

## Tests

`blade test` runs `tests/round_trip.saw` (empty, small, text, incompressible and
four-megabyte inputs) and `tests/refusals.saw` (corrupt blocks, a limit that is
too small, limits that are not sizes).

`image/` is a freestanding package that round-trips a buffer on a booted
image. It builds with `blade build --target <triple>` in that directory for
each of the three bare-metal triples. `tools/blade_lane.py` builds all three,
and boots the riscv32 and aarch64 images under QEMU when `qemu-system-riscv32`
and `qemu-system-aarch64` are installed. The ESP32-S3 image is built and
linked, not booted. The image's runtime arena is 64 KiB because compression
needs the 16 KiB state.
