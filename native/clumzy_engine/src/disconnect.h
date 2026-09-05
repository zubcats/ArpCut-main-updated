#ifndef DISCONNECT_H
#define DISCONNECT_H

#include "iup.h"  // Include necessary IUP headers

// Declaration of the function
void Set_Disconnect_inboundCheckbox(const char* value);
void Set_Disconnect_outboundCheckbox(const char* value);
void clumzy_apply_disconnect(int inbound, int outbound);

#endif // DISCONNECT_H

