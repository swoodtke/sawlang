# Saw syntax for Neovim / Vim

Classic regex-based syntax highlighting + filetype settings for `.saw`
files (keywords, builtin/std types, traits, attributes, numeric
literals incl. fixed-width suffixes, strings with `{interpolation}`
and `\u{}` escapes, comments, operators). No build step; works in Vim
too. A Tree-sitter grammar is future work (tracked with the LSP item).

## Install

**lazy.nvim**
```lua
{ dir = "~/Projects/claudes-lang/editor/nvim", name = "saw" }
```

**vim-plug**
```vim
Plug '~/Projects/claudes-lang/editor/nvim'
```

**No plugin manager**
```vim
set runtimepath+=~/Projects/claudes-lang/editor/nvim
```

Reserved-but-unimplemented keywords (`unsafe`, `defer`, `do`,
`generic`) highlight as errors on purpose — they don't parse today.
