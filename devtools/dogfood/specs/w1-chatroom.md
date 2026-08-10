# Spec w1-chatroom — loopback broadcast server

Build a TCP broadcast ("chat") server and its clients in ONE program,
communicating over loopback.

Behavior:
- A server listens on an OS-assigned loopback port. It accepts exactly
  4 client connections, then serves them: every line a client sends is
  broadcast to ALL 4 clients (sender included) as `<client-id>: <line>`
  where client-id is the accept order (0..=3).
- 4 clients connect concurrently; each sends 5 messages `msg <j>` for
  j in 0..=4, one at a time, reading broadcasts as they arrive; each
  client counts every broadcast line it receives.
- After each client has received 20 broadcast lines (4 senders × 5),
  it disconnects; when all clients are done the server shuts down and
  the program exits.
- The server and the clients must run concurrently within the program
  (the server must be serving while clients are still sending).

Output (exactly, after everything completes):
- One line per client, in client-id order: `client <i> received 20`
- `server broadcast <T> lines` where T == 80 (20 lines × 4 recipients)
- `done`

Acceptance:
- Exact output above, identical across runs; exit code 0; no hang
  (a stuck read must not deadlock the program).
- Message ORDER within the streams may vary; only the counts are
  asserted, which is why the output asserts counts.
