# Blade Package Manager - Implementation Plan

This document outlines the Saw language features required to implement `blade`, the Saw package manager. Features are organized by phase, with each phase building on the previous.

## Current Saw Capabilities

**What we have:**
- Functions, structs, enums with generics
- Pattern matching, optionals, closures
- Traits and extensions
- Resource management (Deinit, CustomCopy, NoCopy)
- Move semantics
- Fixed-size arrays, tuples
- For/while loops with iterators

**What we need:**
- ~~FFI for system calls~~ ✅ Done
- ~~Dynamic collections (Vector, Map)~~ ✅ Done
- ~~StringBuilder~~ ✅ Done
- ~~String methods (len, trim, contains, split, join, etc.)~~ ✅ Done
- ~~File I/O~~ ✅ Done (File, Directory, Data structs)
- ~~Process spawning~~ ✅ Done (Command struct)
- ~~Module system~~ ✅ Done (imports, visibility, packages)
- ~~Command-line argument parsing~~ ✅ Done (Env.args)
- ~~Error handling (Result, try/catch)~~ ✅ Done

---

## Phase 1: Foundation (FFI & Runtime) ✅ MOSTLY COMPLETE

*Goal: Enable Saw to interact with the operating system.*

### 1.1 Foreign Function Interface (FFI)
**Priority: CRITICAL - Blocks everything else**

```saw
// Syntax for declaring external C functions
extern "C" {
    func puts(s: *Int8) -> Int32
    func malloc(size: Int) -> *Int8
    func free(ptr: *Int8)
    func open(path: *Int8, flags: Int32) -> Int32
    func read(fd: Int32, buf: *Int8, count: Int) -> Int
    func write(fd: Int32, buf: *Int8, count: Int) -> Int
    func close(fd: Int32) -> Int32
}
```

**Tasks:**
- [x] Add `extern "C"` block parsing to parser
- [x] Add raw pointer types: `UnsafePointer<T>` (with optional `?` for nullable)
- [x] Add fixed-width integer types: `Int8`, `Int16`, `Int32`, `Int64`
- [x] Generate LLVM `declare` statements for external functions
- [x] Handle C calling conventions in codegen
- [x] String to `UnsafePointer<Int8>` conversion via `as` cast
- [ ] Add `unsafe` blocks for pointer operations (deferred - currently all pointer ops allowed)

**Tests needed:**
- [x] Call libc `puts` to print a string
- [x] Call `malloc`/`free` for manual memory
- [x] Read/write to a file descriptor (File struct uses POSIX open/read/write/close)

### 1.2 Raw Pointer Operations
**Priority: HIGH - Required for FFI**

```saw
// Pointer operations (only in unsafe blocks)
unsafe {
    let ptr = malloc(100)
    ptr[0] = 65           // Write byte
    let byte = ptr[0]     // Read byte
    let offset = ptr + 10 // Pointer arithmetic
    free(ptr)
}
```

**Tasks:**
- [ ] Parse `unsafe { }` blocks (deferred - pointer ops currently unrestricted)
- [x] Allow pointer indexing `ptr[i]`
- [ ] Allow pointer arithmetic `ptr + n` (use indexing instead)
- [x] Pointer casting between types (`as` operator)
- [x] Null pointer via optional: `UnsafePointer<T>?` with `None`

### 1.3 Fixed-Width Integer Types
**Priority: HIGH - Required for FFI**

```saw
let a: Int8 = 127
let b: Int32 = 2147483647
let c: Int64 = 9223372036854775807
let u: UInt8 = 255  // Unsigned variants
```

**Tasks:**
- [x] Add Int8, Int16, Int32, Int64 to type system
- [x] Add UInt8, UInt16, UInt32, UInt64
- [x] Integer literal type inference (defaults to Int/Int64)
- [x] Explicit casts between integer sizes: `x as Int32`
- [ ] Overflow behavior (currently wraps silently)

---

## Phase 2: Dynamic Collections ✅ COMPLETE

*Goal: Resizable data structures for managing dependencies.*

### 2.1 Vector<T> - Dynamic Array ✅
**Priority: HIGH** - COMPLETED

```saw
var items = Vector<Int>()
items.push(10)
items.push(20)
print(items.len())     // 2
if let x = items.get(0) {
    print(x)           // 10
}
items.pop()            // Returns Int?

for item in items.iter() {
    print(item)
}
```

**Tasks:**
- [x] Implement Vector<T> struct with heap allocation (in `sawc/std/vector.saw`)
- [x] `push`, `pop`, `len`, `is_empty`, `clear` methods
- [x] `get(index)` with bounds checking (returns T?)
- [x] Iterator implementation via `iter()` method
- [x] Capacity management and reallocation (`grow()`)
- [x] Implement NoCopy + Deinit for cleanup (prevents double-free)
- [x] Added `sizeof<T>()` builtin for allocation size calculations
- [x] Added std/ directory auto-loading for standard library

### 2.2 Map<K, V> ✅
**Priority: HIGH** - COMPLETED

```saw
var m = Map<Int, Int>()
m.insert(1, 100)
if let v = m.get(1) {
    print(v)  // 100
}
m.remove(1)
```

**Tasks:**
- [x] Implement Map<K, V> with parallel Vectors (O(n) linear search)
- [x] `insert`, `get`, `remove`, `contains_key` methods
- [x] `len`, `is_empty`, `clear` methods
- [ ] Key-value iterator (future enhancement)
- [ ] Hashable trait for O(1) lookup (future enhancement)

### 2.3 StringBuilder ✅
**Priority: MEDIUM** - COMPLETED

```saw
var sb = StringBuilder()
sb.append("Hello")
sb.append(", World!")
print(sb.as_str())  // Hello, World!
```

**Tasks:**
- [x] Mutable string buffer with heap allocation
- [x] `append`, `append_char` operations
- [x] `as_str` for conversion to String
- [x] Added String <-> UnsafePointer<Int8> casting

---

## Phase 3: String Manipulation ✅ MOSTLY COMPLETE

*Goal: Parse TOML, process CLI args, handle paths.*

### 3.1 String Methods
**Priority: HIGH** - COMPLETED

```saw
let s = "  hello, world  "
s.trim()                    // "hello, world"
s.split(", ")               // ["hello", "world"]
s.starts_with("hello")      // true
s.ends_with("world")        // true (after trim)
s.contains(",")             // true
s.replace(",", ";")         // "  hello; world  "
s.to_uppercase()            // "  HELLO, WORLD  "
s.len()                     // 16

let parts = "a/b/c".split("/")
let joined = parts.join("-")  // "a-b-c"
```

**Tasks:**
- [x] `len()` - byte count (implemented in `std/string.saw`)
- [x] `trim()`, `trim_start()`, `trim_end()`
- [x] `split(separator)` returning Vector<String>
- [x] `starts_with(prefix)`, `ends_with(suffix)`
- [x] `contains(substring)`
- [x] `replace(old, new)`
- [x] `to_uppercase()`, `to_lowercase()`
- [x] `is_empty()` - bonus method added
- [x] `byte_at(index)` - bonus method for low-level access
- [x] `equals(other)` - string comparison
- [x] `join(separator)` for Vector<String> (via generic specialization)
- [ ] `chars()` iterator
- [ ] Substring/slice syntax: `s[0..5]`

### 3.2 String Formatting
**Priority: MEDIUM**

```saw
let name = "Alice"
let age = 30
let msg = "Name: {name}, Age: {age}"  // Already have this

// Extended formatting
let hex = "{value:x}"    // Hexadecimal
let pad = "{num:>5}"     // Right-align with padding
```

**Tasks:**
- [ ] Format specifiers in string interpolation
- [ ] Number formatting (decimal, hex, binary)
- [ ] Alignment and padding

---

## Phase 4: File System ✅ MOSTLY COMPLETE

*Goal: Read Saw.toml, write Saw.lock, check file existence.*

### 4.1 File I/O ✅
**Priority: CRITICAL for blade** - COMPLETED

```saw
// Open files
let f = File.open("data.txt")?       // Open for reading
let f = File.create("data.txt")?     // Create/truncate for writing
let f = File.open_append("log.txt")? // Open for appending

// Read/write using Data (byte buffer)
let data = f.read()?                  // Read entire file
let data = f.read(1024)?              // Read up to 1024 bytes
let bytes_written = f.write(data)?    // Write Data to file

// Seeking
f.seek_start(0)?                      // Seek to beginning
f.seek_end(0)?                        // Seek to end
let pos = f.position()?               // Get current position

// Static utilities
File.exists("data.txt")               // Check if exists
File.remove("data.txt")               // Delete file
File.rename("old.txt", "new.txt")     // Rename file

// Directory operations
let files = Directory.list(".")?      // Returns Vector<String>?
Directory.create("mydir")             // Create directory (0755)
Directory.remove("mydir")             // Remove empty directory
let cwd = Directory.current()?        // Get current directory
Directory.set_current("/tmp")         // Change directory
Directory.exists("mydir")             // Check existence
```

**Tasks:**
- [x] `File.open(path)`, `File.create(path)`, `File.open_append(path)` -> File?
- [x] `f.read()`, `f.read(size)` -> Data? (reads bytes)
- [x] `f.write(data)` -> Int? (bytes written)
- [x] `File.exists(path)` -> Bool
- [x] `File.remove(path)` -> Bool
- [x] `File.rename(from, to)` -> Bool
- [x] Seek operations: `seek_start()`, `seek_current()`, `seek_end()`, `position()`
- [x] NoCopy implementation with automatic fd cleanup in deinit
- [x] `Directory.list(path)` -> Vector<String>?
- [x] `Directory.create(path)`, `Directory.remove(path)` -> Bool
- [x] `Directory.current()` -> String?, `Directory.set_current(path)` -> Bool
- [x] `Directory.exists(path)` -> Bool
- [ ] `fs.read_to_string(path)` convenience wrapper (can use File + Data.as_string)
- [ ] `fs.write_string(path, content)` convenience wrapper
- [ ] `file.read_line()` for line-by-line reading

### 4.2 Path Handling ✅
**Priority: MEDIUM** - COMPLETED

```saw
let p = Path(s: "src/main.saw")
p.parent()          // Path? -> Path("src")
p.file_name()       // String? -> "main.saw"
p.stem()            // String? -> "main"
p.ext()             // String? -> "saw"
p.join("other")     // Path("src/main.saw/other")
p.is_absolute()     // false

Directory.current() // Path? - current working directory
```

**Tasks:**
- [x] Path struct with platform-aware separators
- [x] `parent()`, `file_name()`, `stem()`, `ext()`
- [x] `join()` for path concatenation
- [x] `is_absolute()`, `is_relative()`, `is_empty()`
- [x] File and Directory APIs updated to use Path exclusively
- [ ] `canonicalize()` for resolving symlinks (future)

---

## Phase 5: Process & Environment ✅ COMPLETE

*Goal: Run sawc, git, and read CLI arguments.*

### 5.1 Command Execution ✅
**Priority: CRITICAL for blade** - COMPLETED

```saw
// Create and run a command
var cmd = Command(program: "echo")
cmd.arg("hello")
cmd.arg("world")

// Capture output
if let result = cmd.output() {
    print("stdout: {result.stdout}")
    print("success: {result.success()}")
    print("exit code: {result.exit_code}")
}

// Or just run (inherits stdio)
let exit_code = cmd.run()
```

**Tasks:**
- [x] `Command` struct with builder pattern (in `std/process.saw`)
- [x] `.arg()` for adding arguments
- [x] `.output()` -> CommandOutput? (captures stdout)
- [x] `.run()` -> Int32 (inherits stdio, returns exit code)
- [x] `CommandOutput` with `.stdout`, `.exit_code`, `.success()`
- [ ] `.args()` for multiple arguments at once (future)
- [ ] `.env()` for environment variables (future)
- [ ] `.current_dir()` for working directory (future)
- [ ] `.spawn()` for background processes (future)
- [ ] stderr capture (future)

### 5.2 Environment Access ✅
**Priority: HIGH** - COMPLETED

```saw
// Command line arguments
let argc = Env.argc()           // Number of args
if let program = Env.arg(0) {   // First arg (program name)
    print(program)
}
let args = Env.args()           // All args as Vector<String>

// Environment variables
if let home = Env.get("HOME") {
    print(home)
}
Env.set("MY_VAR", "value")
Env.unset("MY_VAR")
Env.contains("PATH")            // Check if set

// Current directory (wraps Directory)
if let cwd = Env.cwd() {
    print(cwd.as_str())
}
Env.set_cwd(Path(s: "/tmp"))
```

**Tasks:**
- [x] `Env.argc()` -> Int
- [x] `Env.arg(index)` -> String?
- [x] `Env.args()` -> Vector<String>
- [x] `Env.get(name)` -> String?
- [x] `Env.set(name, value)` -> Bool
- [x] `Env.unset(name)` -> Bool
- [x] `Env.contains(name)` -> Bool
- [x] `Env.cwd()` -> Path? (wraps Directory.current)
- [x] `Env.set_cwd(path)` -> Bool (wraps Directory.set_current)
- [ ] `Env.home_dir()` -> Path? (future)

---

## Phase 6: Error Handling ✅ COMPLETE

*Goal: Proper Result types and error propagation.*

### 6.1 Result Type & Error Handling ✅
**Priority: HIGH** - COMPLETED

```saw
enum Result<T, E> {
    case Ok(value: T),
    case Err(error: E)
}

// Auto-wrap returns - just return T or E
func parse_number(valid: Bool) -> Result<Int, ParseError> {
    if valid {
        return 42              // Auto-wraps to Ok(value: 42)
    }
    return ParseError(code: 1) // Auto-wraps to Err(error: ...)
}

// try variants
let x = try parse_number(true)           // Propagates Err to caller
let y = try? parse_number(false)         // Returns Int? (None on Err)
let z = try! parse_number(true)          // Force unwrap (panics on Err)

// Inline catch
let value = try parse_number(false) catch { 0 }  // Fallback value

// Block try-catch
try {
    let a = try op1()
    let b = try op2()
} catch {
    print(error.code)  // 'error' variable available
}

// Multiple error types with match
try {
    let n = try parse_number(false)
    let f = try read_file(path)
} catch {
    match error {
        case ParseError(e) -> print(e.code),
        case IoError(e) -> print(e.status)
    }
}
```

**Tasks:**
- [x] Built-in Result<T, E> enum
- [x] Auto-wrap returns: returning T wraps in Ok, returning E wraps in Err
- [x] `try expr` for error propagation to caller
- [x] `try? expr` converts Result to Optional (None on Err)
- [x] `try! expr` force unwrap (panics on Err)
- [x] `try expr catch { }` inline catch with fallback
- [x] `try { } catch { }` block catch with implicit `error` variable
- [x] Multiple error types auto-union with match support in catch
- [x] Pattern matching on Result with `match`
- [ ] Error trait with `message()` method (optional - errors work without it)

---

## Phase 7: Module System ✅ COMPLETE

*Goal: Split blade into multiple files.*

### 7.1 Imports & Modules ✅
**Priority: CRITICAL for blade** - COMPLETED

```saw
// In src/main.saw
import cli
import manifest
import builder

func main() {
    let args = cli.parse()
    // ...
}

// In src/cli.saw
module cli

public func parse() -> Args {
    // ...
}

func private_helper() {
    // Not accessible outside this module
}
```

**Tasks:**
- [x] `import module_name` syntax
- [x] `import module.{Symbol1, Symbol2}` selective imports
- [x] `import foo.*` glob imports
- [x] `module name` declaration at file top
- [x] `public` visibility modifier
- [x] `public(package)` and `public(parent)` visibility
- [x] File-to-module name mapping
- [x] Compiler multi-file compilation
- [x] Dependency ordering (topological sort)
- [x] Circular import detection
- [x] Per-module namespace resolution
- [x] Visibility enforcement across modules

### 7.2 Package Structure ✅
**Priority: MEDIUM** - COMPLETED

```
my-package/
├── Saw.toml         # Package manifest
├── init.saw         # Optional facade (defines public API)
├── src/
│   ├── lib.saw      # Library entry point
│   ├── main.saw     # Binary entry point
│   └── utils/
│       ├── init.saw # Module facade
│       └── parse.saw
```

**Tasks:**
- [x] `Saw.toml` package manifest parsing
- [x] `init.saw` facade files for defining public API
- [x] `export` statements for re-exporting symbols
- [x] Subdirectory modules
- [x] `import package.submodule` syntax
- [x] Inline modules: `module name { ... }`
- [x] External modules: `module name` (loads name.saw)

---

## Phase 8: Blade Implementation

*Once Phases 1-7 are complete, blade can be implemented in Saw.*

### 8.1 CLI Parser
- Parse `blade build`, `blade run`, `blade new`, etc.
- Handle flags like `--release`, `--lib`
- Pass arguments to compiled binary (`-- args`)

### 8.2 TOML Parser
- Implement basic TOML parsing in Saw
- Parse `Saw.toml` manifest files
- Support sections: `[package]`, `[dependencies]`, `[dev-dependencies]`

### 8.3 Dependency Resolver
- Parse semver version strings
- Resolve compatible versions
- Generate `Saw.lock` with exact versions
- Detect version conflicts

### 8.4 Builder
- Topological sort of dependencies
- Invoke `sawc` for each package
- Incremental builds (file modification times)
- Link final binary

### 8.5 Git Integration
- Clone repositories via `git` command
- Checkout specific branches/tags
- Cache downloaded dependencies

---

## Implementation Order

**Milestone 1: Hello World via FFI** ✅ COMPLETE (Phase 1)
- FFI basics, call libc puts()
- malloc/free for heap allocation
- Vector<T> using malloc/realloc/free

**Milestone 1.5: Collections & Strings** ✅ COMPLETE (Phase 2-3)
- Vector<T>, Map<K, V> dynamic collections
- StringBuilder for string building
- String methods (len, trim, contains, starts_with, ends_with, replace, split, etc.)
- Vector<String>.join via generic extension specialization

**Milestone 2: File Operations** ✅ COMPLETE (Phase 4)
- File struct with open/create/read/write/seek
- Directory struct with list/create/remove/current
- Data type for byte buffers with refcounted storage
- Variadic FFI support for system calls
- NoCopy return safety check in typechecker

**Milestone 3: Run External Commands** ✅ COMPLETE (Phase 5)
- Command struct with arg(), run(), output()
- Env struct with argc, arg, args, get, set, cwd

**Milestone 4: Multi-File Projects** ✅ COMPLETE (Phase 7)
- Import system with module, public, export keywords
- Visibility: public, public(package), public(parent), private (default)
- Saw.toml package manifest and init.saw facades
- Per-module namespace resolution and type checking

**Milestone 4.5: Error Handling** ✅ COMPLETE (Phase 6)
- Result<T, E> with auto-wrap returns
- try/try?/try! operators
- Inline and block catch syntax
- Multiple error types with match in catch

**Milestone 5: Minimal blade** (Phase 8.1-8.4) ⬅️ NEXT
- `blade build` for local projects
- No network, no lock file

**Milestone 6: Full blade** (Phase 8.5 + networking)
- Git dependencies
- Registry support
- Lock file generation

---

## Dependencies Between Features

```
FFI (1.1) ──────┬──► Vec/Map (2.x) ──► TOML Parser
                │
                ├──► File I/O (4.x) ──► Read Saw.toml
                │
                └──► Process (5.x) ──► Run sawc/git

Module System (7.x) ──► Multi-file blade

String Methods (3.x) ──► CLI parsing, Path handling
```

---

## Notes

- **Bootstrap Strategy**: A Python script will compile the first version of blade. After that, blade builds itself.
- **Testing**: Each feature should have comprehensive tests before moving to the next phase.
- **Standard Library**: `std.*` modules will be written in Saw using FFI to libc.
- **Platform Support**: Initially target macOS/Linux. Windows support is deferred.
