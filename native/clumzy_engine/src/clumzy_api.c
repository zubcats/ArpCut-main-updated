#include <string.h>
#include <stdlib.h>
#include <time.h>
#include <locale.h>
#include <Windows.h>
#include "common.h"
#include "clumzy_api.h"
#include "lag.h"
#include "drop.h"
#include "disconnect.h"
#include "bandwidth.h"
#include "throttle.h"
#include "duplicate.h"
#include "ood.h"
#include "tamper.h"
#include "reset.h"

int NetworkType = 0;
static volatile short g_running = 0;

int clumzy_engine_init(void) {
    setlocale(LC_NUMERIC, "C");
    srand((unsigned int)time(NULL));
    NetworkType = 0;
    parameterized = 0;
    sendState = SEND_STATUS_NONE;
    g_running = 0;
    return 1;
}

int clumzy_is_admin(void) {
    return IsRunAsAdmin() ? 1 : 0;
}

void clumzy_set_network(int network_type) {
    NetworkType = network_type;
}

int clumzy_start(const char *filter, char *err, int errlen) {
    char buf[MSG_BUFSIZE];
    buf[0] = '\0';
    if (!filter) {
        filter = "true";
    }
    if (g_running) {
        divertStop();
        g_running = 0;
    }
    if (divertStart(filter, buf) == 0) {
        if (err && errlen > 0) {
            strncpy(err, buf, (size_t)errlen - 1);
            err[errlen - 1] = '\0';
        }
        g_running = 0;
        return 0;
    }
    g_running = 1;
    if (err && errlen > 0) {
        err[0] = '\0';
    }
    return 1;
}

void clumzy_stop(void) {
    int ix;
    divertStop();
    g_running = 0;
    sendState = SEND_STATUS_NONE;
    for (ix = 0; ix < MODULE_CNT; ++ix) {
        modules[ix]->processTriggered = 0;
    }
}

int clumzy_is_running(void) {
    return g_running ? 1 : 0;
}

void clumzy_enable(const char *short_name, int on) {
    int ix;
    if (!short_name) {
        return;
    }
    for (ix = 0; ix < MODULE_CNT; ++ix) {
        if (strcmp(modules[ix]->shortName, short_name) == 0) {
            InterlockedExchange16(modules[ix]->enabledFlag, I2S(on ? 1 : 0));
            return;
        }
    }
}

void clumzy_lag(int inbound, int outbound, int time_ms) {
    clumzy_apply_lag(inbound, outbound, time_ms);
}

void clumzy_drop(int inbound, int outbound, float chance_pct) {
    clumzy_apply_drop(inbound, outbound, chance_pct);
}

void clumzy_disconnect(int inbound, int outbound) {
    clumzy_apply_disconnect(inbound, outbound);
}

void clumzy_bandwidth(int inbound, int outbound, int limit, int queue_size, int kb) {
    clumzy_apply_bandwidth(inbound, outbound, limit, queue_size, kb);
}

void clumzy_throttle(int inbound, int outbound, float chance_pct, int timeframe_ms, int drop_throttled) {
    clumzy_apply_throttle(inbound, outbound, chance_pct, timeframe_ms, drop_throttled);
}

void clumzy_duplicate(int inbound, int outbound, float chance_pct, int count) {
    clumzy_apply_duplicate(inbound, outbound, chance_pct, count);
}

void clumzy_ood(int inbound, int outbound, float chance_pct) {
    clumzy_apply_ood(inbound, outbound, chance_pct);
}

void clumzy_tamper(int inbound, int outbound, float chance_pct, int redo_checksum) {
    clumzy_apply_tamper(inbound, outbound, chance_pct, redo_checksum);
}

void clumzy_reset(int inbound, int outbound, float chance_pct) {
    clumzy_apply_reset(inbound, outbound, chance_pct);
}

void clumzy_reset_next(void) {
    clumzy_apply_reset_next();
}
