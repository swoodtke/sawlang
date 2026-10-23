/* The C side of export_narrow_integers.saw: each export called with a narrow
   argument cut from a wider value, so a register's upper bits are whatever
   the convention leaves there, and each narrow result read back widened. */
#include <stdint.h>

int64_t probe_export_i8(int8_t v);
int64_t probe_export_i16(int16_t v);
int64_t probe_export_u8(uint8_t v);
int64_t probe_export_u16(uint16_t v);
int8_t probe_export_give_i8(void);
int16_t probe_export_give_i16(void);
uint8_t probe_export_give_u8(void);
uint16_t probe_export_give_u16(void);

int64_t probe_call_i8(int64_t wide) { return probe_export_i8((int8_t)wide); }
int64_t probe_call_i16(int64_t wide) { return probe_export_i16((int16_t)wide); }
int64_t probe_call_u8(int64_t wide) { return probe_export_u8((uint8_t)wide); }
int64_t probe_call_u16(int64_t wide) { return probe_export_u16((uint16_t)wide); }
int64_t probe_read_i8(void) { return probe_export_give_i8(); }
int64_t probe_read_i16(void) { return probe_export_give_i16(); }
int64_t probe_read_u8(void) { return probe_export_give_u8(); }
int64_t probe_read_u16(void) { return probe_export_give_u16(); }
