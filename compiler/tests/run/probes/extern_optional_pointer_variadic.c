/* The C side of extern_optional_pointer_variadic.saw: of `count` pointer
   arguments after it, a digit each, 0 for NULL and 1 otherwise. */
#include <stdarg.h>
#include <stdint.h>
#include <stddef.h>

int64_t probe_null_digits(int64_t count, ...) {
    va_list ap;
    va_start(ap, count);
    int64_t digits = 0;
    for (int64_t k = 0; k < count; k++) {
        void *p = va_arg(ap, void *);
        digits = digits * 10 + (p == NULL ? 0 : 1);
    }
    va_end(ap);
    return digits;
}
