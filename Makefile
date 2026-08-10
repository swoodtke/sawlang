# Saw Language Makefile

.PHONY: test test-verbose test-sequential clean help blade-bootstrap sos-test lexdiff astdiff irdet irdet-all gmgate abidoc bttable bttable-sizes lldbtest ircontract preludegate icebreadcrumb

# Default target
all: test

# Run all tests
test:
	@python3 test_runner.py

# Run tests with verbose output
test-verbose:
	@python3 test_runner.py -v

# Run a specific test by name
test-filter:
	@python3 test_runner.py -f $(FILTER)

# Blade self-hosting bootstrap (design 64 B8): Blade builds + tests Blade
# through its own resolve/lock/module-path/incremental pipeline.
blade-bootstrap:
	@python3 tools/blade_bootstrap.py

# SOS QEMU tests (designs 112, 140, 162): build the freestanding kernel AND the
# root-server sosimg (via blade), stitch them, and run under QEMU `virt` on
# EVERY architecture SOS targets — riscv32 and arm64 — asserting the console
# transcript + emulator exit status. Either failing is red. Requires host tools
# qemu-system-riscv32, qemu-system-aarch64, ld.lld, and clang (the harness
# probes for them and prints install hints if missing). `--arch <name>` runs one,
# for development.
sos-test:
	@python3 tools/sos_runner.py

# Differential lexer harness (design 116): build the Saw lexer, then diff its
# canonical token dump against sawc's Python lexer over every tracked .saw file.
# Zero mismatches is the acceptance bar.
lexdiff:
	@python3 tools/lexdiff.py

# AST dump acceptance harness (design 126 R11), the parser-port oracle: dump
# every tracked .saw file and require the dump to be COMPLETE (no node type
# falls through a dispatcher) and byte-stable across runs.
astdiff:
	@python3 tools/astdiff.py

# Compiler output determinism (design 126 R2): compile a corpus sample twice,
# in fresh processes under differing PYTHONHASHSEED, and require byte-identical
# IR. Zero non-reproducible files is the acceptance bar.
#
# `irdet` samples 40 examples — fast enough for per-commit use. `irdet-all`
# sweeps the WHOLE corpus and is the standard for a brief's final gate battery
# (design 146 unit D): a random sample cannot police a whole-corpus property,
# and design 141 proved it — two nondeterministic emission orders had been
# sitting in the tree unnoticed until adding two unrelated examples reshuffled
# the sample onto one of them.
# The harness itself is written in SAW (design 155, the first devtool port):
# `devtools/irdet/`, built here the way lexdiff builds the Saw lexer. It still
# drives the PYTHON sawc — the tool is Saw, the compiler under test is not.
IRDET_BIN := .build/irdetbin

$(IRDET_BIN): devtools/irdet/src/main.saw
	@python3 sawc/sawc.py devtools/irdet/src/main.saw -o $(IRDET_BIN)

irdet: $(IRDET_BIN)
	@./$(IRDET_BIN)

irdet-all: $(IRDET_BIN)
	@./$(IRDET_BIN) --all

# Ownership gate under Guard Malloc (design 159 unit 4). A missing retain does
# not fail an ordinary run: the surplus release lands in a freed-but-mapped
# block and the program exits 0, which is how DF-151b sat in a green tree from
# design 73 onward. Guard Malloc unmaps freed blocks, so an over-release faults
# at the instruction that made it. Small curated lanes — the ownership oracles
# only, since a page per allocation is far too slow for the whole suite.
#
# TWO lanes since design 192 unit 4: `ownership` is about values (copies,
# retains, drops, containers) and `concurrency` is the same failures where the
# value lives in a heap-resident coroutine frame or crosses a task boundary.
# `make gmgate` runs both; `--lane <name>` runs one.
gmgate:
	@python3 tools/gmgate.py

# Runtime-ABI document check (design 149 unit c): the compiler checks exported
# seams against the signatures in rt/ABI.md, so the document has to describe
# exactly the frozen symbol set. Neither kind of drift shows up in a build.
abidoc:
	@python3 tools/test_runtime_abi_doc.py

# Properties of the emitted IR the examples suite structurally cannot express
# (design 187): a `-c` compile embeds the same coroutine frames a hosted one
# does (the suite runs programs, so it never looks at an object file), and every
# `__saw_rt_*` seam the compiler declares has the width rt/ABI.md gives it on a
# 32-bit target as well as a 64-bit one (the suite does not cross-compile, and
# `word` and `Int64` are the same type where it runs). Both were miscompiles.
ircontract:
	@python3 tools/test_ir_contract.py

# The prelude allowlist against the spec's own module table (design 188 unit 7).
# `IMPORT_REQUIRED_STD_MODULES` decides which std names need an import and the
# spec's table documents the same partition; nothing tied them together, so they
# drifted and `SpinLock`/`SlabHead` were reachable bare for as long as the spec
# said otherwise. Drift is invisible from both ends — the compiler is consistent
# and the document is coherent — so it needs a test of its own.
preludegate:
	@python3 tools/test_prelude_gate_doc.py

# The internal-compiler-error report (design 192 unit 2). An ICE is a path no
# corpus program takes, so nothing else exercises the machinery: delete the
# breadcrumb stamp from a dispatch and the whole suite still passes. This
# injects a failure into the typechecker and into codegen and reads the report
# back — one line, a FILE:LINE:COL anchor, the AST node's name, and the full
# traceback under SAW_DEBUG=1.
icebreadcrumb:
	@python3 tools/test_ice_breadcrumb.py

# The logical-backtrace table (design 158 unit 1): cross-check every frame
# record against the frame-layout report the same compile produced. A wrong
# offset there reads a live frame at the wrong place and prints a confident lie,
# which no runtime test would catch. `bttable-sizes` reports what the
# always-linked table costs per program.
bttable:
	@python3 tools/test_bt_table.py

bttable-sizes:
	@python3 tools/test_bt_table.py --sizes

# The lldb commands (design 158 unit 2): drive a real lldb over a real binary
# and check that `saw table` / `saw tasks` / `saw bt` agree with the fixture.
# Skips where lldb is absent, and downgrades to the no-process tier where lldb
# cannot attach.
lldbtest:
	@python3 tools/test_lldb_saw.py

# Clean build artifacts. Everything generated lives under a `.build/` directory
# — the repo's own, plus one per Saw package holding that package's per-target
# output (design 143). Nothing generated sits beside a source file, so these two
# lines are the whole of it.
clean:
	@rm -rf .build/*
	@rm -rf blade/.build libs/*/.build
	@echo "Cleaned build directories"

# Run tests sequentially (original behavior)
test-sequential:
	@python3 test_runner.py --sequential

# Show help
help:
	@echo "Saw Language Makefile"
	@echo ""
	@echo "Available targets:"
	@echo "  make test            - Run all tests in parallel (default)"
	@echo "  make test-verbose    - Run tests with verbose output"
	@echo "  make test-sequential - Run tests sequentially (no parallelism)"
	@echo "  make test-filter     - Run tests matching FILTER pattern"
	@echo "                         Example: make test-filter FILTER=enum"
	@echo "  make sos-test        - Build + boot the SOS kernel + root server under QEMU (riscv32 AND arm64)"
	@echo "  make lexdiff         - Diff the Saw lexer against sawc's over the corpus"
	@echo "  make astdiff         - Dump every tracked .saw file and require stability"
	@echo "  make irdet           - IR determinism over a 40-example sample (per commit)"
	@echo "  make irdet-all       - IR determinism over the WHOLE corpus (final gate)"
	@echo "  make gmgate          - Ownership + concurrency oracles under Guard Malloc (macOS)"
	@echo "  make abidoc          - rt/ABI.md describes exactly the frozen seam set"
	@echo "  make ircontract      - -c embeds what hosted embeds; seam widths match rt/ABI.md"
	@echo "  make preludegate     - The import gate matches LANGUAGE_SPEC's module table"
	@echo "  make icebreadcrumb   - An internal compiler error reports one located line"
	@echo "  make bttable         - Task-backtrace table vs the frame layouts"
	@echo "  make bttable-sizes   - What the always-linked backtrace table costs"
	@echo "  make lldbtest        - saw tasks / saw bt under a real lldb"
	@echo "  make clean           - Remove build artifacts"
	@echo "  make help            - Show this help message"
	@echo ""
	@echo "Test runner options (via python3 test_runner.py):"
	@echo "  -j N, --jobs N       - Number of parallel workers"
	@echo "  --sequential         - Run tests sequentially"
