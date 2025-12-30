# Saw Package Manager - Implementation Roadmap (Prioritized)

To build `blade` in Saw, the compiler (`sawc`) and standard library need significant expansion. The current language supports logic and data structures well, but lacks interaction with the outside world (I/O, Network, Process).

## Phase 1: The Bridge (FFI & Basic I/O)
*Goal: Allow Saw code to read files and run shell commands.*

1.  **[CRITICAL] Foreign Function Interface (FFI)**
    *   **Feature:** `extern "C"` support in `sawc`.
    *   **Why:** We cannot implement file I/O or networking in pure Saw without rewriting an OS kernel. We need to call `libc` (open, read, write) or existing C libraries.
    *   **Task:** Add `extern` keyword parsing, type mapping (Saw `Int` -> C `long`, Saw `String` -> C `char*`), and LLVM generation for external calls.

2.  **Standard Library: `std.fs` (File System)**
    *   **Feature:** File reading/writing wrappers around C functions.
    *   **Why:** `blade` needs to read `Saw.toml` and write `Saw.lock`.
    *   **API:** `File.open`, `File.read_to_string`, `File.write`, `fs.exists`, `fs.create_dir_all`.

3.  **Standard Library: `std.process`**
    *   **Feature:** Process spawning.
    *   **Why:** `blade` needs to invoke `sawc` to compile dependencies and `git` to fetch repos.
    *   **API:** `Command.new("sawc").arg("...").output()`.

4.  **Standard Library: `std.env`**
    *   **Feature:** Access to command line arguments and environment variables.
    *   **Why:** To read user input (`blade build`) and configuration.

## Phase 2: The Module System
*Goal: Support multi-file projects and imports.*

5.  **Module & Import Support**
    *   **Feature:** `import` keyword and file-to-module mapping.
    *   **Why:** `blade` cannot be written in a single file. It needs `cli.saw`, `manifest.saw`, `builder.saw`, etc.
    *   **Task:** Update `sawc` to resolve import paths, parse multiple files, and link them.

6.  **Visibility Modifiers**
    *   **Feature:** `public` keyword.
    *   **Why:** To expose library functions to consumers while keeping helpers private.

## Phase 3: Data Processing
*Goal: Parse manifests and lockfiles.*

7.  **Standard Library: Collections (`Vec`, `Map`)**
    *   **Feature:** Dynamic arrays and HashMaps.
    *   **Why:** Dependency graphs are complex structures. We need `Map<String, Version>` and `Vec<Dependency>`.
    *   **Task:** Implement in `builtin.saw` (likely wrapping C++ stdlib or writing raw Saw resizing logic).

8.  **Standard Library: String Manipulation**
    *   **Feature:** `split`, `trim`, `starts_with`, `contains`.
    *   **Why:** Parsing TOML and CLI arguments requires string processing.

9.  **TOML Parser (Userland)**
    *   **Task:** Write a TOML parser in Saw.
    *   **Dependency:** Requires `std.fs` and String manipulation.

## Phase 4: Networking (Registry)
*Goal: Fetch packages from the internet.*

10. **Standard Library: `std.net` (HTTP Client)**
    *   **Feature:** HTTP GET support.
    *   **Why:** To download packages from the registry.
    *   **Implementation:** Bind to `libcurl` via FFI initially. Implementing a raw TCP/TLS stack is too much for now.

## Phase 5: Self-Hosting
*Goal: `blade` builds itself.*

11. **Bootstrap Script**
    *   **Task:** Write a Makefile or Python script that compiles the first version of `blade`.
    *   **End State:** Once `blade` binary exists, it should be able to run `blade build` in its own directory.