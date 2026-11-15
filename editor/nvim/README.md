# Saw syntax for Neovim and Vim

Regex-based syntax highlighting and filetype settings for `.saw` files, and
`Saw.toml` and `Saw.lock` read as TOML. There is no build step, and the same
files work in Vim.

The highlighting follows the lexical layer in `GRAMMAR.md` (section 2):

- the keywords, and the contextual words only in the position where each has a
  meaning (`type` before a name, `const` in a generic list, `any` before a
  trait, the effect slot after a parameter list such as `consumes unsafe sync`,
  `import` and `module` at the head of an item, `private` before a field,
  `lends`, a capture list's `copy`); everywhere else they are identifiers, so
  `let type = 7` is not highlighted as a keyword;
- the primitive types, the prelude's types and traits, and the std types most
  programs import;
- integer literals with `_` separators and width suffixes (`0x8000_0000u32`,
  `2_u8`), floats, closure shorthand parameters (`$0`), and the `#file`,
  `#line` and `#function` directives;
- strings with their escapes (`\{` and `\}` are literal braces) and
  `{interpolation}`;
- `//` comments, with `///` and `//!` doc comments set apart;
- attributes (`@synthesize`, `@export`, `@test(...)`).

## Install

Replace `/path/to/sawlang` with your checkout.

**lazy.nvim**
```lua
{ dir = "/path/to/sawlang/editor/nvim", name = "saw" }
```

**vim-plug**
```vim
Plug '/path/to/sawlang/editor/nvim'
```

**No plugin manager**
```vim
set runtimepath+=/path/to/sawlang/editor/nvim
```
