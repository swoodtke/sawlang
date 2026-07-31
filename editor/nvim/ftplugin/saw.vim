" Filetype plugin for Saw
if exists("b:did_ftplugin")
  finish
endif
let b:did_ftplugin = 1

setlocal commentstring=//\ %s
setlocal comments=://
setlocal suffixesadd=.saw
setlocal expandtab shiftwidth=4 softtabstop=4
setlocal formatoptions-=t formatoptions+=croql

" simple brace-based indentation (no dedicated indent file yet)
setlocal autoindent smartindent

let b:undo_ftplugin = "setl cms< com< sua< et< sw< sts< fo< ai< si<"
