/* The C side of extern_optional_pointer_parameter.saw: what each pointer
   parameter received, -1 for NULL and the first byte otherwise. */
#include <stdint.h>
#include <stddef.h>

int64_t probe_first_byte(const uint8_t *p) {
    return p == NULL ? -1 : p[0];
}

int64_t probe_first_byte_const(const uint8_t *p) {
    return p == NULL ? -1 : p[0];
}
