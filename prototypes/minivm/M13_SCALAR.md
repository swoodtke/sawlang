# M13: checked Scalar construction

Planned after unsigned parsing, before StringBuilder. The lexer uses only
`try! Scalar(value: cp)` and passes the result to StringBuilder.append. This
slice must distinguish Scalar from Int and prevent source-level fabrication
of an invalid code point. It is not the complete std Scalar or enum surface.

## Representation

Install two reserved nominal builtin records in the existing record table:
Scalar with one private Int raw word, and InvalidScalar with private Int cause
and value words. Their source names cannot be redeclared. Reserve the record
identity explicitly in compiler metadata; do not infer builtin status merely
from a user-chosen field name. These descriptors use the existing fixed typed
layout/Result/ABI machinery, with no runtime allocation.
Install them before declaration collection, use unspellable internal field
names, and reject collisions across structs, enums, statics and functions.
Reject user extensions on either builtin by its stored identity.

Raw record construction and field projection for these two types are forbidden
in source. `Scalar(value: Int)` is an intrinsic returning Result<Scalar,
InvalidScalar>. Lower it with existing checked comparisons and branches:
negative or above 0x10FFFF => Err(out-of-range cause, original input);
0xD800..0xDFFF => Err(surrogate cause, original input); otherwise Ok(raw input).
Initialize the full result including inactive alternatives. Scalar.value()
on a named place returns its Int code point. Temporary Scalar receivers remain
outside this slice, matching current record-method restrictions.
Copy, arguments/results, Optionals and record fields
work as for other data records. No casts to Scalar, Scalar arithmetic, direct
printing or user extensions are introduced.

InvalidScalar is deliberately opaque at this boundary: Result matching can
observe success/failure and bind/copy/forward the error, but source matching on
its OutOfRange/Surrogate payload cases and error formatting remain unsupported.
Preserve both cause and original input internally for later implementation.
Document this limit so it is not mistaken for full std InvalidScalar support.
The flattened construction is [tag, scalar_raw, cause, original]: success
writes [true, input, 0, 0], while failure writes [false, 0, cause, input]. Cause
0 means out of range and 1 means surrogate. The invariant is enforced by the
source frontend; hand-authored IR retains the prototype's existing trust limit.

## Required tests

Valid boundaries 0, 0x7F, 0x80, 0x7FF, 0x800, 0xD7FF, 0xE000, 0xFFFF,
0x10000, 0x10FFFF round-trip via value(). Reject negative/Int.min, 0xD800,
0xDFFF, 0x110000 and Int.max through Err rather than overflow/panic.
Copy/return/nesting preserves nominal type and value. Invalid raw constructors,
raw field reads/writes, wrong labels/arity, integer casts and name collisions
have located diagnostics. Direct lowering inspection/contract checks verify
error cause and original input since that projection is not a source API yet.

Next, StringBuilder.append(Scalar) will encode exactly 1–4 UTF-8 bytes from a
validated Scalar. That integration gets its own byte-boundary tests.
