#ifndef BANDWIDTH_H
#define BANDWIDTH_H

#include "iup.h"  // Include necessary IUP headers

// Declaration of the function
void Set_Bandwidth_inboundCheckbox(const char* value);
void Set_Bandwidth_outboundCheckbox(const char* value);

void Set_Bandwidth_bandwidthInput(const char* value);
void Set_Bandwidth_queueSizeInput(const char* value);
void Set_Bandwidth_speed(const char* value);
void clumzy_apply_bandwidth(int inbound, int outbound, int limit, int queue_size, int kb);


#endif // BANDWIDTH_H

