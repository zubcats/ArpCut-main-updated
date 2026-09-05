#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#ifdef CLUMZY_ENGINE_ONLY
#define CLUMZY_API __declspec(dllexport)
#else
#define CLUMZY_API
#endif

CLUMZY_API int clumzy_engine_init(void);
CLUMZY_API int clumzy_is_admin(void);
CLUMZY_API void clumzy_set_network(int network_type);
CLUMZY_API int clumzy_start(const char *filter, char *err, int errlen);
CLUMZY_API void clumzy_stop(void);
CLUMZY_API int clumzy_is_running(void);
CLUMZY_API void clumzy_enable(const char *short_name, int on);
CLUMZY_API void clumzy_lag(int inbound, int outbound, int time_ms);
CLUMZY_API void clumzy_drop(int inbound, int outbound, float chance_pct);
CLUMZY_API void clumzy_disconnect(int inbound, int outbound);
CLUMZY_API void clumzy_bandwidth(int inbound, int outbound, int limit, int queue_size, int kb);
CLUMZY_API void clumzy_throttle(int inbound, int outbound, float chance_pct, int timeframe_ms, int drop_throttled);
CLUMZY_API void clumzy_duplicate(int inbound, int outbound, float chance_pct, int count);
CLUMZY_API void clumzy_ood(int inbound, int outbound, float chance_pct);
CLUMZY_API void clumzy_tamper(int inbound, int outbound, float chance_pct, int redo_checksum);
CLUMZY_API void clumzy_reset(int inbound, int outbound, float chance_pct);
CLUMZY_API void clumzy_reset_next(void);

#ifdef __cplusplus
}
#endif
