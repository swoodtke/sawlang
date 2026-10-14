# A ledger two patches appended to under a union merge

Each chose V02 for its new row, and the merge kept both. The rows differ only
after the id, and they sit in two sections, so the check reads the whole file.

## First section

| Row | Checks | Covered by |
|---|---|---|
| V01 | a value moved out is not used again | `V01_use_after_move.saw` |
| V02 | a value moved into a closure is not used again | `V02_move_into_closure.saw` |

## Second section

| Row | Checks | Covered by |
|---|---|---|
| V03 | a consumed receiver is released field by field | `V03_consumed_receiver.saw` |
| V02 | a field moved out and assigned again is released once | `V02_field_refill.saw` |
