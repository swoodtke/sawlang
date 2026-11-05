"""The complexity lane's generated programs: one long construct of size N per
shape, each beside the same small `main` so that only the construct grows.

    ctor    one struct construction with N labelled arguments
    lets    one function of N `let` statements, each naming the last
    calls   one function of N method calls on one local
    match   one `match` with N literal arms
    params  one call passing N arguments to an N-parameter function
    yields  one function with N suspension points
"""

SHAPES = ("ctor", "lets", "calls", "match", "params", "yields")

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
    elif shape == "params":
        lines += ["func g(" + ", ".join("p%d: Int" % k for k in range(n)) + ") -> Int {",
                  "    p0 + p%d" % (n - 1), "}", ""]
        lines += ["func f(s: &S) -> Int {", "    g(" + ", ".join("s.v.len()" for _ in range(n)) + ")", "}"]
    else:
        raise ValueError("unknown shape %r" % shape)
    lines += _MAIN
    return "\n".join(lines)
