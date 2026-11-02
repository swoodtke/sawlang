/* The C side of funcpointer_c_convention.saw: Saw's function pointers called
   from C with narrow arguments cut from wider values, their narrow results
   read back widened, and a C function handed to Saw as a pointer. */
#include <stdint.h>

int64_t probe_fp_call_i8(int8_t (*cb)(int8_t), int64_t wide) { return cb((int8_t)wide); }
int64_t probe_fp_call_u16(uint16_t (*cb)(uint16_t), int64_t wide) { return cb((uint16_t)wide); }

static int8_t c_twice_i8(int8_t v) { return (int8_t)(v * 2); }

int8_t (*probe_fp_c_twice(void))(int8_t) { return c_twice_i8; }
