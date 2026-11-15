" Vim syntax file
" Language:     Saw
" Maintainer:   the Saw project (editor/nvim in the Saw repository)
" License:      Apache-2.0 WITH LLVM-exception
"
" The lexical layer is GRAMMAR.md section 2: its keyword list, its contextual
" words, its literals and its comments. A contextual word is an ordinary
" identifier outside its position, so each one below is matched only where
" GRAMMAR.md gives it a meaning.

if exists("b:current_syntax")
  finish
endif

syn case match

" ---------------------------------------------------------------- keywords
" The keywords proper: never an identifier.
syn keyword sawKeyword func let var static extern init struct enum trait
syn keyword sawKeyword extension public unsafe as not
syn keyword sawConditional if else guard match case
syn keyword sawRepeat while for in
syn keyword sawStatement return break continue move borrow borrows lend
syn keyword sawException try catch
syn keyword sawBoolean true false
syn keyword sawConstant None
syn keyword sawSelf self Self

" `try?` and `try!` are prefix operators of their own.
syn match sawException "\<try[!?]"

" --------------------------------------------------------- contextual words
" Each is a keyword only in the position named, and an identifier elsewhere.

" At the head of a top-level item.
syn match sawKeyword "^\s*\zs\%(import\|module\|export\)\>\ze\s"
" `public(package)`, `public(parent)`.
syn match sawKeyword "\%(\<public\s*(\s*\)\@<=\%(package\|parent\)\>"
" Before a struct field's name.
syn match sawKeyword "^\s*\zsprivate\>\ze\s\+\h"
" A type alias or an associated type: `type` followed by a name.
syn match sawKeyword "\<type\>\ze\s\+\h"
" A const generic parameter: `<const N: Int>`.
syn match sawKeyword "\%([<,]\s*\)\@<=const\>\ze\s\+\h"
" An existential: `any Trait`.
syn match sawKeyword "\<any\>\ze\s\+\h"
" The effect slot after a parameter list: `) consumes unsafe sync -> T`, and a
" function type's `sendable`. Matched after `)` and after another effect word.
syn match sawEffect "\%()\s*\%(\%(consumes\|unsafe\|constexpr\|blocking\|sync\|sendable\|escaping\)\s\+\)*\)\@<=\%(consumes\|constexpr\|blocking\|sync\|sendable\|escaping\)\>"
" `blocking func` in an extern block.
syn match sawEffect "\<blocking\>\ze\s\+func\>"
" `lends self`, `lends name`.
syn match sawStatement "\<lends\>\ze\s\+\h"
" A capture list's `copy` mode: `[copy w]`, `[a, copy w]`.
syn match sawKeyword "\%([[,]\s*\)\@<=copy\>\ze\s\+\h"

" ------------------------------------------------------------------- types
" The primitive types, ordinary identifiers that name types.
syn keyword sawType Int UInt Int8 Int16 Int32 Int64 UInt8 UInt16 UInt32 UInt64
syn keyword sawType Float Bool String Void Never Byte
" The prelude's types, and the std types most programs import.
syn keyword sawStdType Optional Result Vector Map Set Box Arc Atomic
syn keyword sawStdType StringBuilder Hasher Ordering Duration Task TaskGroup Thread
syn keyword sawStdType Range RangeInclusive RangeFrom RangeTo RangeToInclusive RangeFull
syn keyword sawStdType Allocator GlobalAllocator AllocError
syn keyword sawStdType UnsafePointer UnsafeConstPointer UnsafeMemory UnsafeMutableInterior
syn keyword sawStdType Data File Directory Path Instant Mutex Channel
" The prelude's traits.
syn keyword sawTrait Copy ExplicitCopy NoCopy NoMove Deinit ZeroInit Iterator
syn keyword sawTrait Equatable Comparable Hashable Printable Error
syn keyword sawTrait Send Sync UnsafeSend UnsafeSync
syn keyword sawTrait Serialize Deserialize Encoder Decoder
" The cases of Optional and Result.
syn keyword sawConstant Some Ok Err
" A declaration's name after the word that introduces it.
syn match sawTypeDef "\%(\<\%(struct\|enum\|trait\|extension\)\s\+\)\@<=\u\w*"
syn match sawTypeDef "\%(\<type\s\+\)\@<=\u\w*"

" -------------------------------------------------------------- attributes
syn match sawAttribute "@\h\w*" nextgroup=sawAttrArgs
syn region sawAttrArgs matchgroup=sawAttribute start="(" end=")" contained contains=sawString,sawNumber

" -------------------------------------------------------------- directives
syn match sawDirective "#\%(file\|line\|function\)\>"

" ----------------------------------------------------------------- numbers
" A width suffix may follow one `_`: `2u8`, `2_u8`.
syn match sawNumber "\<\d\%(_\?\d\)*\%(_\?[iu]\%(8\|16\|32\|64\)\)\?\>"
syn match sawNumber "\<0x\x\%(_\?\x\)*\%(_\?[iu]\%(8\|16\|32\|64\)\)\?\>"
syn match sawNumber "\<0b[01]\%(_\?[01]\)*\%(_\?[iu]\%(8\|16\|32\|64\)\)\?\>"
syn match sawNumber "\<0o\o\%(_\?\o\)*\%(_\?[iu]\%(8\|16\|32\|64\)\)\?\>"
" A float has a digit on each side of the point, and no exponent or suffix.
syn match sawFloat "\<\d\%(_\?\d\)*\.\d\%(_\?\d\)*\>"

" A closure's shorthand parameter: `$0`.
syn match sawShorthand "\$\d\+"

" ----------------------------------------------------------------- strings
" Escapes: \\ \" \n \t \r \0 \u{...}, and \{ \} for literal braces.
syn match sawEscape contained "\\[\\\"ntr0{}]"
syn match sawEscape contained "\\u{\x\{1,6}}"
" An unescaped `{` opens an interpolation; `{}` is a format placeholder.
syn region sawInterp matchgroup=sawInterpDelim start="{" end="}" contained contains=TOP oneline
syn region sawString start=+"+ skip=+\\\\\|\\"+ end=+"+ contains=sawEscape,sawInterp

" ---------------------------------------------------------------- comments
" There are no block comments. A line that starts with `///` or `//!` is a
" doc comment; `////` is an ordinary one.
syn keyword sawTodo contained TODO FIXME XXX NOTE HACK
syn match sawComment "//.*$" contains=sawTodo,@Spell
syn match sawDocComment "^\s*\zs///\%([^/].*\)\?$" contains=sawTodo,@Spell
syn match sawDocComment "^\s*\zs//!.*$" contains=sawTodo,@Spell

" --------------------------------------------------------------- operators
syn match sawOperator "->"
syn match sawOperator "\.\.[.=]\?"
syn match sawOperator "??"
syn match sawOperator "?\."
syn match sawOperator "&[+*-]"
syn match sawOperator "&var\>"
" A postfix `!` forces an Optional: after a name, `)` or `]`.
syn match sawOperator "\%(\w\|)\|\]\)\@<=!"

" ---------------------------------------------------------------- builtins
syn keyword sawBuiltin print panic assert sleep cancelled
" `static_assert(`, and `sizeof`/`alignof` in a const-generic argument.
syn match sawBuiltin "\<static_assert\>\ze\s*("
syn match sawBuiltin "\<\%(sizeof\|alignof\)\>\ze\s*<"

" ------------------------------------------------------------------ links
hi def link sawKeyword      Keyword
hi def link sawEffect       StorageClass
hi def link sawConditional  Conditional
hi def link sawRepeat       Repeat
hi def link sawStatement    Statement
hi def link sawException    Exception
hi def link sawBoolean      Boolean
hi def link sawConstant     Constant
hi def link sawSelf         Special
hi def link sawType         Type
hi def link sawStdType      Type
hi def link sawTrait        Structure
hi def link sawTypeDef      Typedef
hi def link sawAttribute    PreProc
hi def link sawDirective    PreProc
hi def link sawNumber       Number
hi def link sawFloat        Float
hi def link sawShorthand    Identifier
hi def link sawString       String
hi def link sawEscape       SpecialChar
hi def link sawInterpDelim  Special
hi def link sawComment      Comment
hi def link sawDocComment   SpecialComment
hi def link sawTodo         Todo
hi def link sawOperator     Operator
hi def link sawBuiltin      Function

let b:current_syntax = "saw"
