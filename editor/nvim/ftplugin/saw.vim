" Filetype plugin for Saw
if exists("b:did_ftplugin")
  finish
endif
let b:did_ftplugin = 1

setlocal commentstring=//\ %s
" Doc comments (`///`, `//!`) continue as themselves, plain ones as `//`.
setlocal comments=:///,://!,://
setlocal suffixesadd=.saw
setlocal expandtab shiftwidth=4 softtabstop=4
setlocal formatoptions-=t formatoptions+=croql

" Brace-based indentation; there is no indent file.
setlocal autoindent smartindent

let b:undo_ftplugin = "setl cms< com< sua< et< sw< sts< fo< ai< si<"
