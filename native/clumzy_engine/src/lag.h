#ifndef LAG_H
#define LAG_H

#include "iup.h"  // Include necessary IUP headers

// Declaration of the function
void Set_Lag_inboundCheckbox(const char* value);
void Set_Lag_outboundCheckbox(const char* value);
void Set_Lag_timeInput(const char* value);
void clumzy_apply_lag(int inbound, int outbound, int time_ms);


#endif // LAG_H
