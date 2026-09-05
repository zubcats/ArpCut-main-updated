#ifndef DROP_H
#define DROP_H

#include "iup.h"  // Include necessary IUP headers

// Declaration of the function
void Set_Drop_inboundCheckbox(const char* value);
void Set_Drop_outboundCheckbox(const char* value);
void Set_Drop_chanceInput(const char* value);
void clumzy_apply_drop(int inbound, int outbound, float chance_pct);

#endif // DROP_H
