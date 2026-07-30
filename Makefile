# Saw Language Makefile

.PHONY: test test-verbose test-sequential clean help blade-bootstrap

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

# Clean build artifacts
clean:
	@rm -rf .build/*
	@echo "Cleaned build directory"

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
	@echo "  make clean           - Remove build artifacts"
	@echo "  make help            - Show this help message"
	@echo ""
	@echo "Test runner options (via python3 test_runner.py):"
	@echo "  -j N, --jobs N       - Number of parallel workers"
	@echo "  --sequential         - Run tests sequentially"
