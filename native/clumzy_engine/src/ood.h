#ifndef OUTOFORDER_H
#define OUTOFORDER_H

#include "iup.h"  // Include necessary IUP headers

// Declaration of the function
void Set_OutOfOrder_inboundCheckbox(const char* value);
void Set_OutOfOrder_outboundCheckbox(const char* value);

void Set_OutOfOrder_chanceInput(const char* value);
void Set_OutOfOrder_countInput(const char* value);
void clumzy_apply_ood(int inbound, int outbound, float chance_pct);


#endif // OUTOFORDER_H

