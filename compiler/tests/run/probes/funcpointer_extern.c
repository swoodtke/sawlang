/* The C side of funcpointer_extern.saw: libc's own `strcmp` and `free`,
   handed over as Saw function pointers, called back from C. */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

int64_t probe_fp_compare_with(int32_t (*cmp)(const char *, const char *), const char *a, const char *b) {
    int32_t r = cmp(a, b);
    return r < 0 ? -1 : (r > 0 ? 1 : 0);
}

uint8_t *probe_fp_block(void) {
    uint8_t *p = malloc(32);
    memset(p, 7, 32);
    return p;
}

int64_t probe_fp_release_with(void (*release)(uint8_t *)) {
    release(probe_fp_block());
    return 1;
}
