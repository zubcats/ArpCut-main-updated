#ifndef DUPLICATE_H
#define DUPLICATE_H

#include "iup.h"  // Include necessary IUP headers

// Declaration of the function
void Set_Duplicate_inboundCheckbox(const char* value);
void Set_Duplicate_outboundCheckbox(const char* value);

void Set_Duplicate_chanceInput(const char* value);
void Set_Duplicate_countInput(const char* value);
void clumzy_apply_duplicate(int inbound, int outbound, float chance_pct, int count);


#endif // DUPLICATE_H

