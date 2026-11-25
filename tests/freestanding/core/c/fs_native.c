// A freestanding C function of eight Int32 arguments, called from Saw through
// `fscore`. The first few travel in registers and the rest on the stack, so
// the answer holds only when Saw's calling convention and this object's agree
// at every position, each Xtensa ABI included. No header: the types are the
// compiler's own.

__INT32_TYPE__ fs_native_horner8(__INT32_TYPE__ a, __INT32_TYPE__ b, __INT32_TYPE__ c,
                                 __INT32_TYPE__ d, __INT32_TYPE__ e, __INT32_TYPE__ f,
                                 __INT32_TYPE__ g, __INT32_TYPE__ h) {
    // Base ten, so each argument's value and position show in the answer.
    return ((((((a * 10 + b) * 10 + c) * 10 + d) * 10 + e) * 10 + f) * 10 + g) * 10 + h;
}
