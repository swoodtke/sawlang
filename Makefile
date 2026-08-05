# Saw Language Makefile

.PHONY: test test-verbose test-sequential clean help blade-bootstrap sos-test lexdiff astdiff irdet

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

# SOS M0 QEMU smoke tests (design 112): build the freestanding riscv32 kernel
# and run it under QEMU `virt`, asserting the UART banner + emulator exit status.
# Requires host tools qemu-system-riscv32, ld.lld, and clang (the harness probes
# for them and prints install hints if missing).
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
irdet:
	@python3 tools/irdet.py

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
	@echo "  make sos-test        - Build + run the SOS M0 riscv32 kernel under QEMU"
	@echo "  make clean           - Remove build artifacts"
	@echo "  make help            - Show this help message"
	@echo ""
	@echo "Test runner options (via python3 test_runner.py):"
	@echo "  -j N, --jobs N       - Number of parallel workers"
	@echo "  --sequential         - Run tests sequentially"
