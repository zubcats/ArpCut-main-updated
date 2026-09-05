#include <Windows.h>
#include "common.h"

Module* modules[MODULE_CNT] = {
    &lagModule,
    &dropModule,
    &disconnectModule,
    &bandwidthModule,
    &throttleModule,
    &dupModule,
    &oodModule,
    &tamperModule,
    &resetModule,
};

volatile short sendState = SEND_STATUS_NONE;
BOOL parameterized = 0;
