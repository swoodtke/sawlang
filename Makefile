# Saw Language Makefile

.PHONY: test test-verbose clean help

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

# Clean build artifacts
clean:
	@rm -rf .build/*
	@echo "Cleaned build directory"

# Show help
help:
	@echo "Saw Language Makefile"
	@echo ""
	@echo "Available targets:"
	@echo "  make test          - Run all tests (default)"
	@echo "  make test-verbose  - Run tests with verbose output"
	@echo "  make test-filter   - Run tests matching FILTER pattern"
	@echo "                       Example: make test-filter FILTER=enum"
	@echo "  make clean         - Remove build artifacts"
	@echo "  make help          - Show this help message"
