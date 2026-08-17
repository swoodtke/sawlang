" Vim syntax file
" Language:     Saw
" Maintainer:   the Saw project (editor/nvim in the Saw repo)
" Last Change:  2026 Jul 31
" License:      Apache-2.0 WITH LLVM-exception

if exists("b:current_syntax")
  finish
endif

syn case match

" ---------------------------------------------------------------- keywords
syn keyword sawKeyword func let var static extern init deinit
syn keyword sawKeyword struct enum trait extension
" `type` is CONTEXTUAL (DF-232b): a keyword only when it declares an alias,
" i.e. followed by a name. As a field, label or binding (`e.type`,
" `f(type: 1)`, `let type = 7`) it is an ordinary identifier.
syn match sawKeyword "\<type\>\(\s\+\w\)\@="
syn keyword sawConditional if else guard match case
syn keyword sawRepeat while for in
syn keyword sawStatement return break continue move
syn keyword sawKeyword import module public package parent
syn keyword sawException try catch
syn keyword sawKeyword sync escaping any as not
syn keyword sawReserved unsafe defer do generic
syn keyword sawBoolean true false
syn keyword sawConstant None
syn keyword sawSelf self Self

" try! / try? operator forms
syn match sawException "\<try[!?]"

" ------------------------------------------------------------------- types
" builtin value types
syn keyword sawType Int UInt Int8 Int16 Int32 Int64 UInt8 UInt16 UInt32 UInt64
syn keyword sawType Float Bool String Void Never
" std / builtin nominal types
syn keyword sawStdType Vector Map Set Box Arc Mutex Channel Task TaskGroup
syn keyword sawStdType TaskHandle Result StringBuilder Hasher Ordering
syn keyword sawStdType Duration Instant Data File Directory Path
syn keyword sawStdType UnsafePointer UnsafeConstPointer UnsafeMemory Atomic
syn keyword sawStdType Allocator Global GlobalAllocator Range RangeInclusive
" builtin traits
syn keyword sawTrait Copy ImplicitCopy ExplicitCopy NoCopy Deinit Iterator
syn keyword sawTrait Equatable Comparable Hashable Printable Error Send Sync
syn keyword sawTrait Resumable
" a definition introduces a type name
syn match sawTypeDef "\(\<\%(struct\|enum\|trait\|extension\|type\)\s\+\)\@<=\u\w*"

" -------------------------------------------------------------- attributes
syn match sawAttribute "@\w\+" nextgroup=sawAttrArgs
syn region sawAttrArgs matchgroup=sawAttribute start="(" end=")" contained contains=sawString

" ----------------------------------------------------------------- numbers
" decimal (with _ separators and optional fixed-width suffix)
syn match sawNumber "\<\d[0-9_]*\%(_\?[iu]\%(8\|16\|32\|64\)\)\?\>"
" hex / binary / octal
syn match sawNumber "\<0x[0-9a-fA-F_]\+\%(_\?[iu]\%(8\|16\|32\|64\)\)\?\>"
syn match sawNumber "\<0b[01_]\+\%(_\?[iu]\%(8\|16\|32\|64\)\)\?\>"
syn match sawNumber "\<0o[0-7_]\+\%(_\?[iu]\%(8\|16\|32\|64\)\)\?\>"
" float
syn match sawFloat "\<\d[0-9_]*\.\d[0-9_]*\%([eE][+-]\?\d\+\)\?\>"

" ----------------------------------------------------------------- strings
" escapes: \\ \" \n \t \r \0? and \u{...}; literal braces are {{ and }}
syn match sawEscape contained "\\[\\\"ntr]"
syn match sawEscape contained "\\u{[0-9a-fA-F]\{1,6}}"
syn match sawBraceEscape contained "{{"
syn match sawBraceEscape contained "}}"
" interpolation: {expr} inside a string
syn region sawInterp matchgroup=sawInterpDelim start="{" end="}" contained contains=sawNumber,sawFloat,sawBoolean,sawSelf,sawOperator oneline
syn region sawString start=+"+ skip=+\\"+ end=+"+ contains=sawEscape,sawBraceEscape,sawInterp

" ---------------------------------------------------------------- comments
syn keyword sawTodo contained TODO FIXME XXX NOTE HACK
syn match sawComment "//.*$" contains=sawTodo,@Spell

" --------------------------------------------------------------- operators
syn match sawOperator "->"
syn match sawOperator "\.\.=\?"
syn match sawOperator "??"
syn match sawOperator "?\."
syn match sawOperator "&[+*-]"
syn match sawOperator "&var\>"
" force-unwrap ! (postfix after identifier/paren/bracket)
syn match sawOperator "\%(\w\|)\|\]\)\@<=!"

" ---------------------------------------------------------------- builtins
syn keyword sawBuiltin print panic assert sizeof alignof static_assert
syn keyword sawBuiltin yield_now sleep spawn cancelled

" ------------------------------------------------------------------ links
hi def link sawKeyword      Keyword
hi def link sawConditional  Conditional
hi def link sawRepeat       Repeat
hi def link sawStatement    Statement
hi def link sawException    Exception
hi def link sawReserved     Error
hi def link sawBoolean      Boolean
hi def link sawConstant     Constant
hi def link sawSelf         Special
hi def link sawType         Type
hi def link sawStdType      Type
hi def link sawTrait        Structure
hi def link sawTypeDef      Typedef
hi def link sawAttribute    PreProc
hi def link sawNumber       Number
hi def link sawFloat        Float
hi def link sawString       String
hi def link sawEscape       SpecialChar
hi def link sawBraceEscape  SpecialChar
hi def link sawInterpDelim  Special
hi def link sawComment      Comment
hi def link sawTodo         Todo
hi def link sawOperator     Operator
hi def link sawBuiltin      Function

let b:current_syntax = "saw"
