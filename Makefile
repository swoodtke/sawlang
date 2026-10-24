# Saw Language Makefile

.PHONY: all clean help blade install compiler-test gmgate abidoc toolchain

# Default target
all: compiler-test

# The install story (design 238 unit 3, D-b1): put `sawc`, `sawc0` and `blade`
# on a $PATH. There is nothing to package — `sawc` is the self-hosted compiler,
# which its shim builds from this tree on first use (compiler/tools/build.py),
# `sawc0` forwards to v0.18.0's compiler in the v0 checkout (`SAWLANG_V0_ROOT`,
# else the pinned tag, fetched and cached), and Blade is built from Saw source —
# so `bin/` holds three shims and `install` symlinks them onto a prefix. An
# installed name therefore always means THIS tree, and re-installing after a
# `git pull` is unnecessary.
#
#   make install                    # -> ~/.local/bin
#   make install PREFIX=/usr/local/bin
#
# Blade is built first because its shim execs a binary rather than a script.
# Blade is frozen in v0.18.0's language (blade/README.md), so the build goes
# through `bin/sawc0`.
PREFIX ?= $(HOME)/.local/bin
BLADE_BIN := .build/blade

blade:
	@bin/sawc0 blade/src/main.saw -o $(BLADE_BIN) \
		--module-path blade=blade/src \
		--module-path toml=libs/toml/src \
		--module-path semver=libs/semver/src \
		--module-path imgformat=libs/imgformat/src

install: blade
	@mkdir -p $(PREFIX)
	@ln -sf $(abspath bin/sawc) $(PREFIX)/sawc
	@ln -sf $(abspath bin/sawc0) $(PREFIX)/sawc0
	@ln -sf $(abspath bin/blade) $(PREFIX)/blade
	@echo "Installed sawc, sawc0 and blade -> $(PREFIX)"
	@echo "  (add it to your PATH if it is not already there)"

# The self-hosted compiler's tests (compiler/README.md): its unit programs, the
# golden token fixtures, and the subset checker over its own source.
compiler-test:
	@python3 compiler/tests/run.py

# Ownership gate under Guard Malloc (design 159 unit 4). A missing retain does
# not fail an ordinary run: the surplus release lands in a freed-but-mapped
# block and the program exits 0. Guard Malloc unmaps freed blocks, so an
# over-release faults at the instruction that made it. Small curated lanes —
# the ownership oracles only, since a page per allocation is far too slow for
# the whole corpus.
#
# TWO lanes since design 192 unit 4: `ownership` is about values (copies,
# retains, drops, containers) and `concurrency` is the same failures where the
# value lives in a heap-resident coroutine frame or crosses a task boundary.
# `make gmgate` runs both; `--lane <name>` runs one.
gmgate:
	@python3 tools/gmgate.py

# Runtime-ABI document check (design 149 unit c): the compiler checks exported
# seams against the signatures in runtime/ABI.md, so the document has to describe
# exactly the frozen symbol set. Neither kind of drift shows up in a build.
abidoc:
	@python3 tools/test_runtime_abi_doc.py

# The toolchain resolver (design 238 unit 4): the one place a consumer of this
# repository locates `sawc`, `blade` and the packages it compiles against. All
# four resolution steps, the pin's version check and the refusal that names
# them — driven with a fabricated environment, so no step depends on what
# happens to be installed and the fetch never touches the network.
toolchain:
	@python3 tools/test_toolchain.py

# Clean build artifacts. Everything generated lives under a `.build/` directory
# — the repo's own, plus one per Saw package holding that package's per-target
# output (design 143). Nothing generated sits beside a source file, so these two
# lines are the whole of it.
clean:
	@rm -rf .build/*
	@rm -rf blade/.build libs/*/.build
	@echo "Cleaned build directories"

# Show help
help:
	@echo "Saw Language Makefile"
	@echo ""
	@echo "Available targets:"
	@echo "  make compiler-test   - The self-hosted compiler's tests (the default)"
	@echo "  make blade           - Build the package manager into .build/blade (through sawc0)"
	@echo "  make install         - Put sawc, sawc0 + blade on a PATH (PREFIX=~/.local/bin)"
	@echo "  make gmgate          - Ownership + concurrency oracles under Guard Malloc (macOS)"
	@echo "  make abidoc          - runtime/ABI.md describes exactly the frozen seam set"
	@echo "  make toolchain       - The toolchain resolver: four steps, version check, refusal"
	@echo "  make clean           - Remove build artifacts"
	@echo "  make help            - Show this help message"
	@echo ""
	@echo "The per-patch gate is ./build.sh test; the full battery is tools/battery.sh."
