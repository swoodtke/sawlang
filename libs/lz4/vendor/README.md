# Vendored lz4

`lz4/` holds three files from the lz4 project's `lib/` directory, unmodified:

| File | SHA-256 |
|---|---|
| `lz4.c` | `9396f7de527bc8435de9c7569fb7998e56545a84b4f3c2d808c0235c01774539` |
| `lz4.h` | `26b82efc53d1570f3b54eef02e9c4764c1ad374ff03cac04e2ced5ea4d4c552f` |
| `LICENSE` | `8b58c446121a109ccf32edc094bba3010a3d85e4ee3702950db55e4d3e87736c` |

- Version: 1.10.0 (`LZ4_VERSION_MAJOR 1`, `LZ4_VERSION_MINOR 10`)
- Source: <https://github.com/lz4/lz4/archive/refs/tags/v1.10.0.tar.gz>
- SHA-256 of that tarball: `537512904744b35e232912055ccf8ec66d768639ff3abe5788d90d792ec5f48b`
- License: BSD 2-Clause for the library (`LICENSE`, and the header of each source file).

Only the block codec (`lz4.c`, `lz4.h`) is vendored. The frame, high-compression
and file layers are not used by `libs/lz4`.

To update, fetch the new release tarball into an empty directory, check that
`lz4.c` and `lz4.h` still define `LZ4_FREESTANDING` the way
`../Saw.toml` relies on, replace the three files, and record the new version,
URL and hashes here.
