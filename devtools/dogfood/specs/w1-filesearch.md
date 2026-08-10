# Spec w1-filesearch — concurrent file search

Build a program that generates a small file tree, then searches it
concurrently and aggregates the results deterministically.

Behavior:
- Setup: under a fresh temporary directory the program creates, write
  12 text files named f00.txt..f11.txt. File i's content is 200 lines;
  line j of file i is `line <j> tag<(i*7 + j*13) mod 50>` (so the
  token `tag17` appears a computable number of times per file).
- Search: for the fixed needle `tag17`, search all 12 files with at
  least 4 concurrent search units (a unit opens, reads, and counts
  matching LINES in one or more whole files; units run concurrently).
- Aggregate: collect per-file counts, then report them SORTED by file
  name regardless of completion order. Clean up the temporary
  directory before exiting.

Output (exactly):
- One line per file, sorted: `f<NN>.txt <count>`
- `total <T>` — the sum
- `done`

Acceptance:
- Counts are fully determined by the content formula; identical output
  across runs; exit code 0.
- File I/O errors must not be silently ignored anywhere (a failed
  open/read/write should stop the program with a clear message —
  exercise your language's error-handling discipline, not a happy
  path).
