#ifndef THROTTLE_H
#define THROTTLE_H

#include "iup.h"  // Include necessary IUP headers

// Declaration of the function
void Set_Throttle_inboundCheckbox(const char* value);
void Set_Throttle_outboundCheckbox(const char* value);

void Set_Throttle_dropThrottledCheckbox(const char* value);
void Set_Throttle_frameInpchanceInputut(const char* value);
void Set_Throttle_frameInput(const char* value);
void clumzy_apply_throttle(int inbound, int outbound, float chance_pct, int timeframe_ms, int drop_throttled);


#endif // THROTTLE_H

