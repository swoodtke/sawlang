# compiler-rt soft-float builtins

The soft-float routines LANGUAGE_SPEC.md's Profiles section says a
freestanding environment supplies on a target with no floating-point unit,
taken from LLVM's compiler-rt so the suite's images link them the way a kernel
would. `tools/freestanding_runner.py` compiles each `.c` file here for the
case's architecture and links the objects beside `../support.c`.

## Source

- Repository: https://github.com/llvm/llvm-project
- Tag: `llvmorg-23.1.3` (commit `0d261d1ca552c95a8f007e061c787ac7132fbcbc`)
- Directory: `compiler-rt/lib/builtins/`
- License: `LICENSE.TXT`, compiler-rt's own (Apache-2.0 WITH LLVM-exception,
  sawlang's license too)

The tag matches the Homebrew LLVM clang the runner picks for riscv32
(23.1.3). The files are plain C, and every clang the runner may pick compiles
them.

The files are unmodified. To update them, fetch the same names from a new tag
and change this file's tag and commit.

## Files

The routines, one per file:

    adddf3.c       __adddf3
    subdf3.c       __subdf3
    muldf3.c       __muldf3
    divdf3.c       __divdf3
    comparedf2.c   __eqdf2 __nedf2 __ltdf2 __ledf2 __gtdf2 __gedf2 __unorddf2
                   (and __cmpdf2)
    fixdfsi.c      __fixdfsi
    fixdfdi.c      __fixdfdi
    fixunsdfsi.c   __fixunsdfsi
    fixunsdfdi.c   __fixunsdfdi
    floatsidf.c    __floatsidf
    floatdidf.c    __floatdidf
    floatunsidf.c  __floatunsidf
    floatundidf.c  __floatundidf
    fp_mode.c      __fe_getround, __fe_raise_inexact (the generic default,
                   which `__adddf3` calls)

The headers and implementation files they include:

    fp_lib.h  fp_mode.h  int_lib.h  int_math.h  int_types.h  int_endianness.h
    int_util.h  int_to_fp.h  int_to_fp_impl.inc  fp_add_impl.inc
    fp_mul_impl.inc  fp_div_impl.inc  fp_compare_impl.inc  fp_fixint_impl.inc
    fp_fixuint_impl.inc
