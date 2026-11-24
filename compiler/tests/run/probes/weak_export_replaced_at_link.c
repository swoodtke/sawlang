#include <stdint.h>

/* The strong definition the weak default of weak_export_replaced_at_link.saw
   yields to at the link. */
int64_t weak_linked_hook(void) {
    return 7;
}
