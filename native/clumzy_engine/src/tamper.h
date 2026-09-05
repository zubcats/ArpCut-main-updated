#ifndef TAMPER_H
#define TAMPER_H

#include "iup.h"  // Include necessary IUP headers

// Declaration of the function
void Set_Tamper_inboundCheckbox(const char* value);
void Set_Tamper_outboundCheckbox(const char* value);

void Set_Tamper_chanceInput(const char* value);
void Set_Tamper_checksumCheckbox(const char* value);
void clumzy_apply_tamper(int inbound, int outbound, float chance_pct, int redo_checksum);


#endif // TAMPER_H

