# Spec w1-pipeline — three-stage channel pipeline

Build a producer → transformer → sink pipeline where the stages run
concurrently and communicate only through message channels.

Behavior:
- Stage 1 (producer): emits the integers 1..=5000, then signals
  completion.
- Stage 2 (transformer): for each received integer v, computes
  h = (h * 31 + v) mod 1000000007 as a running value (h starts at 0)
  AND forwards v unchanged when v is divisible by 7; on upstream
  completion, forwards its final h and signals completion.
- Stage 3 (sink): counts forwarded integers and receives the final h;
  on completion prints the results.
- The three stages must be genuinely concurrent units (the producer
  must not need to finish before the sink starts consuming).

Output (exactly):
- `forwarded <count>` — how many divisible-by-7 values arrived
- `hash <h>` — the transformer's final running value
- `done`

Acceptance:
- count == 714, h is identical across runs, exit code 0.
- The program must not buffer the whole stream in one place (bounded
  memory: channels may buffer, but do not collect all 5000 into an
  array between stages).
