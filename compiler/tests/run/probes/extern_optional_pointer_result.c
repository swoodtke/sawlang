/* The C side of extern_optional_pointer_result.saw: NULL when asked for it,
   else the address of a byte holding 66. */
#include <stdint.h>
#include <stddef.h>

static uint8_t byte = 66;

uint8_t *probe_pointer_or_null(int64_t null) {
    return null ? NULL : &byte;
}

const uint8_t *probe_const_pointer_or_null(int64_t null) {
    return null ? NULL : &byte;
}
