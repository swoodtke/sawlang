/* The C side of extern_narrow_integers.saw: each narrow parameter returned
   widened, and each narrow result cut from a wider value, so a register's
   upper bits are whatever the convention leaves there. */
#include <stdint.h>

int64_t probe_take_i8(int8_t v) { return v; }
int64_t probe_take_i16(int16_t v) { return v; }
int64_t probe_take_u8(uint8_t v) { return v; }
int64_t probe_take_u16(uint16_t v) { return v; }

int8_t probe_give_i8(int64_t wide) { return (int8_t)wide; }
int16_t probe_give_i16(int64_t wide) { return (int16_t)wide; }
uint8_t probe_give_u8(int64_t wide) { return (uint8_t)wide; }
uint16_t probe_give_u16(int64_t wide) { return (uint16_t)wide; }
