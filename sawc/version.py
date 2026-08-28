"""The compiler's version — ONE constant, and what it does and does not promise.

`sawc --version` prints this and nothing else computes it. It exists because a
consumer of the toolchain (design 238 D-b2) has to be able to ask an installed
`sawc` what it is before trusting it with a build: a compiler found on `$PATH`
is otherwise unpinned, and a stale or bleeding-edge one silently produces a
build nobody tested.

THE GRANULARITY ASYMMETRY, STATED RATHER THAN PAPERED OVER (design 238 D-b2,
ruled Aug 24). A consumer pins a toolchain two ways, and the two are not equally
strong. A FETCHED toolchain is pinned by SHA — exact, one tree. An INSTALLED one
can only be checked against whatever this string says, and a semver string
cannot distinguish two commits that share it, which for an unreleased compiler
is the normal case. So a `$PATH` sawc verified by version is a WEAKER guarantee
than a fetched one verified by SHA, deliberately: option (b) of D-b2, cheap and
honest, chosen over teaching `--version` to emit a build SHA because the
language is pre-1.0 and design 231's self-hosted compiler will reshape all of
this anyway.

THE POLICY THAT TRAVELS WITH THAT CHOICE: version bumps are RIGOROUS from here
on. A brief that changes user-visible behaviour bumps this constant, because the
asymmetry above is only tolerable while the string still means something. A
mismatch against a consumer's pin is a loud refusal naming both, never a silent
build — see `tools/toolchain.py`.
"""

SAWC_VERSION = "0.1.0"
