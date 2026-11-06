"""The complexity lane's generated programs: one long construct of size N per
shape, each beside the same small `main` so that only the construct grows.

    ctor    one struct construction with N labelled arguments
    lets    one function of N `let` statements, each naming the last
    calls   one function of N method calls on one local
    match   one `match` with N literal arms
    params  one call passing N arguments to an N-parameter function
    yields  one function with N suspension points
    match_mixed          one `match` over an Int with N arms mixing literals,
                         guarded ranges, guarded wildcards, plain ranges and a
                         guarded literal a later plain one repeats
"""

SHAPES = ("ctor", "lets", "calls", "match", "params", "yields", "match_mixed")

# Arm k of `match_mixed`, by k % 6. A guarded range sends every later row down
# both edges of its test, and its guard's false edge compiles them again: the
# shape that doubled the tree per guarded range (SL-979).
_MIXED = ("case {v} -> {k}", "case {v}..={hi} if x % 7 == {r7} -> {k}", "case _ if x % {m} == {r11} -> {k}",
          "case {v} if x % 3 == 0 -> {k}", "case {lo}..{top} -> {k}", "case {dup} -> {k}")

_HEAD = ["struct S {", "    v: Vector<Int>", "    w: Vector<String>", "}", "", "extension S: NoCopy {}", ""]
_MAIN = ["", "func main() {", "    let s = S(v: Vector<Int>(), w: Vector<String>())", "    let _ = f(&s)", "}", ""]


def program(shape, n):
    """The source of `shape` at size `n`."""
    if shape == "yields":
        lines = ["import std.task", "", "func f(n: Int) -> Int {", "    var total = n"]
        for k in range(n):
            lines += ["    task.yield_now()", "    total = total + %d" % k]
        lines += ["    total", "}", "", "func main() {", "    let t = Task.spawn(f(3))", "    let _ = t.join()", "}", ""]
        return "\n".join(lines)
    lines = list(_HEAD)
    if shape == "ctor":
        lines += ["struct Big {"] + ["    f%d: Vector<Int>" % k for k in range(n)] + ["}", "",
                                                                                   "extension Big: NoCopy {}", ""]
        lines += ["func copy_of(v: &Vector<Int>) -> Vector<Int> {", "    var out = Vector<Int>()", "    var i = 0",
                  "    while i < v.len() {", "        try! out.push(v[i])", "        i = i + 1", "    }",
                  "    move out", "}", ""]
        lines += ["func f(s: &S) -> Big {",
                  "    Big(" + ",\n        ".join("f%d: copy_of(&s.v)" % k for k in range(n)) + ")", "}"]
    elif shape == "lets":
        lines += ["func f(s: &S) -> Int {", "    let a0 = s.v.len()"]
        lines += ["    let a%d = a%d + %d" % (k, k - 1, k) for k in range(1, n)]
        lines += ["    a%d" % (n - 1), "}"]
    elif shape == "calls":
        lines += ["func f(s: &S) -> Vector<Int> {", "    var out = Vector<Int>()"]
        lines += ["    try! out.push(s.v.len() + %d)" % k for k in range(n)]
        lines += ["    move out", "}"]
    elif shape == "match":
        lines += ["func f(s: &S) -> Int {", "    match s.v.len() {"]
        lines += ["        case %d -> %d," % (k, k * 3) for k in range(n)]
        lines += ["        case _ -> 0", "    }", "}"]
    elif shape == "match_mixed":
        lines += ["func f(s: &S) -> Int {", "    let x = s.v.len()", "    match x {"]
        for k in range(n):
            arm = _MIXED[k % 6].format(k=k, v=10 * k, hi=10 * k + 3, r7=k % 7, m=11 + k % 40, r11=k % 11,
                                       lo=10 * k + 5, top=10 * k + 9, dup=10 * (k - 2))
            lines.append("        %s," % arm)
        lines += ["        case _ -> 0", "    }", "}"]
    elif shape == "params":
        lines += ["func g(" + ", ".join("p%d: Int" % k for k in range(n)) + ") -> Int {",
                  "    p0 + p%d" % (n - 1), "}", ""]
        lines += ["func f(s: &S) -> Int {", "    g(" + ", ".join("s.v.len()" for _ in range(n)) + ")", "}"]
    else:
        raise ValueError("unknown shape %r" % shape)
    lines += _MAIN
    return "\n".join(lines)
