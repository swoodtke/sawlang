# Sawlang agent instructions

Read `CLAUDE.md` for the development, testing, worktree, and sawtracker workflow.
Read `.claude/skills/saw-lang/SKILL.md` before writing or reviewing Saw code.

## Implementation delegation

User ruling, confirmed September 17, 2026: **implementation agent choice follows
the lead: Astra/Codex uses Sol (`gpt-5.6-sol`); Fable/Claude uses Opus (`opus`).**
Both leads work in this repository. Dispatch implementation tasks to the
corresponding agents in isolated worktrees before editing implementation files.
This includes parser/compiler source, harnesses, tests, and classification tools.
The parent owns briefs, task boundaries, documentation, tracker coordination,
integration review, and final validation. Astra/Codex uses another implementation
model only when the user asks. The Sol instruction is specific to Astra/Codex;
Fable/Claude follows `CLAUDE.md`, including its explicit model-selection rule
and standing lead-model/Sonnet exceptions. This file does not replace or narrow
those Claude instructions.

Submit finished work through sawtracker patches. User review and merge remain
the landing gate; do not push or commit implementation directly on main.
