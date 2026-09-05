
#ifndef RESET_H
#define RESET_H

#include "iup.h"  // Include necessary IUP headers

// Declaration of the function
void Set_Reset_inboundCheckbox(const char* value);
void Set_Reset_outboundCheckbox(const char* value);

void Set_Reset_chanceInput(const char* value);
void clumzy_apply_reset(int inbound, int outbound, float chance_pct);
void clumzy_apply_reset_next(void);

#endif // RESET_H
