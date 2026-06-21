"""
Advanced Lag (MITM) per-impairment timer gates.

Each row can gate its contribution on a schedule controlled only for that impairment:

- ``{prefix}_timer_on``: when off, gate is always 1.0 (row follows master On / values only).
- ``timer_lag_ms`` / ``timer_pause_ms``: on-phase and off-phase lengths when cycling.

``mitm_adv_*_timer_repeat_forever`` (legacy key name) means **Repeat**: when True, use the
pause duration and repeat lag→pause cycles. When False, a single lag phase applies, then this
row's gate stays at 0 (other impairments keep their own gates).

``timer_runs``: how many full lag→pause cycles while Repeat is on. **-1** means unlimited
(infinite). Values >= 1 cap cycles; 0 means this row's timer contributes nothing (gate 0).

Only the row whose timer expires drops to gate 0; other rows continue independently.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Tuple

Get = Callable[[str], Any]

ROW_PREFIXES: Tuple[str, ...] = (
    'mitm_adv_delay',
    'mitm_adv_jitter',
    'mitm_adv_cap',
    'mitm_adv_loss',
)


def _bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ('0', 'false', 'no', ''):
        return False
    if s in ('1', 'true', 'yes'):
        return True
    return default


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def gate_for_row(t_mono: float, t0: float, get: Get, prefix: str) -> float:
    """
    Return 1.0 when this impairment's timer allows full effect, 0.0 when gated off.
    If the row timer is disabled, always 1.0.
    """
    if not _bool(get(f'{prefix}_timer_on'), False):
        return 1.0
    lag_ms = max(0, _int(get(f'{prefix}_timer_lag_ms'), 0))
    pause_ms = max(0, _int(get(f'{prefix}_timer_pause_ms'), 0))
    if lag_ms <= 0:
        return 1.0
    lag_sec = lag_ms / 1000.0
    use_repeat_cycle = _bool(get(f'{prefix}_timer_repeat_forever'), True)
    if use_repeat_cycle and pause_ms <= 0:
        # Repeat with 0 ms pause would never leave lag phase; use a minimal off-phase.
        pause_sec = 0.001
    else:
        pause_sec = max(0.0, pause_ms / 1000.0)
    period_sec = lag_sec + pause_sec

    elapsed = t_mono - t0
    if elapsed < 0:
        return 1.0

    if not use_repeat_cycle:
        if elapsed >= lag_sec:
            return 0.0
        return 1.0

    if period_sec <= 0:
        return 1.0 if elapsed < lag_sec else 0.0

    runs = _int(get(f'{prefix}_timer_runs'), -1)
    if runs == 0:
        return 0.0
    if runs > 0:
        n_cyc = max(1, min(99_999, runs))
        total_sec = n_cyc * period_sec
        if elapsed >= total_sec:
            return 0.0

    pos = elapsed % period_sec
    if pos < lag_sec:
        return 1.0
    return 0.0


def row_schedule_finished(
    t_mono: float, t0: float, get: Get, prefix: str
) -> bool:
    """True when this row's timer has no more lag phases (finite runs or single-shot)."""
    if not _bool(get(f'{prefix}_timer_on'), False):
        return False
    if not _bool(get(f'{prefix}_on'), False):
        return False
    lag_ms = max(0, _int(get(f'{prefix}_timer_lag_ms'), 0))
    if lag_ms <= 0:
        return False
    lag_sec = lag_ms / 1000.0
    pause_ms = max(0, _int(get(f'{prefix}_timer_pause_ms'), 0))
    use_repeat = _bool(get(f'{prefix}_timer_repeat_forever'), True)
    if use_repeat and pause_ms <= 0:
        pause_sec = 0.001
    else:
        pause_sec = max(0.0, pause_ms / 1000.0)
    period_sec = lag_sec + pause_sec
    elapsed = max(0.0, t_mono - t0)
    runs = _int(get(f'{prefix}_timer_runs'), -1)
    if runs == 0:
        return True
    if not use_repeat:
        return elapsed >= lag_sec
    if runs < 0:
        return False
    n_cyc = max(1, min(99_999, runs))
    return elapsed >= n_cyc * period_sec


def all_enabled_timers_finished(
    t_mono: float,
    t0: float,
    get: Get,
    row_t0: dict[str, float] | None = None,
) -> bool:
    """True when every timer-enabled active row has used up its cycles (session may stop)."""
    saw_timer = False
    for prefix in ROW_PREFIXES:
        if not _bool(get(f'{prefix}_timer_on'), False):
            continue
        if not _bool(get(f'{prefix}_on'), False):
            continue
        saw_timer = True
        rt0 = _row_t0(prefix, t0, row_t0)
        if not row_schedule_finished(t_mono, rt0, get, prefix):
            return False
    return saw_timer


def _row_t0(prefix: str, t0: float, row_t0: dict[str, float] | None) -> float:
    if row_t0 and prefix in row_t0:
        return float(row_t0[prefix])
    return float(t0)


def compute_timer_gates(
    t_mono: float,
    t0: float,
    get: Get,
    row_t0: dict[str, float] | None = None,
) -> Tuple[float, float, float, float]:
    return (
        gate_for_row(t_mono, _row_t0('mitm_adv_delay', t0, row_t0), get, 'mitm_adv_delay'),
        gate_for_row(t_mono, _row_t0('mitm_adv_jitter', t0, row_t0), get, 'mitm_adv_jitter'),
        gate_for_row(t_mono, _row_t0('mitm_adv_cap', t0, row_t0), get, 'mitm_adv_cap'),
        gate_for_row(t_mono, _row_t0('mitm_adv_loss', t0, row_t0), get, 'mitm_adv_loss'),
    )


def base_mitm_params_from_get(get: Get) -> Tuple[int, int, int, int, float, float, int, int]:
    """Same semantics as AdvancedLagSettingsDialog._mitm_effective_params (no timer gates)."""
    d_on = _bool(get('mitm_adv_delay_on'), False)
    d_ms = max(0, min(800, _int(get('mitm_adv_delay_ms'), 0)))
    du = d_ms if d_on and _bool(get('mitm_adv_delay_out'), True) else 0
    dd = d_ms if d_on and _bool(get('mitm_adv_delay_in'), True) else 0

    j_on = _bool(get('mitm_adv_jitter_on'), False)
    j_ms = max(0, min(800, _int(get('mitm_adv_jitter_ms'), 0)))
    ju = j_ms if j_on and _bool(get('mitm_adv_jitter_out'), True) else 0
    jd = j_ms if j_on and _bool(get('mitm_adv_jitter_in'), True) else 0

    c_on = _bool(get('mitm_adv_cap_on'), False)
    cu = (
        _float(get('mitm_adv_cap_out_mbps'), 0.0)
        if c_on and _bool(get('mitm_adv_cap_out'), True)
        else 0.0
    )
    cd = (
        _float(get('mitm_adv_cap_in_mbps'), 0.0)
        if c_on and _bool(get('mitm_adv_cap_in'), True)
        else 0.0
    )

    l_on = _bool(get('mitm_adv_loss_on'), False)
    lp = max(0, min(100, _int(get('mitm_adv_loss_pct'), 0)))
    lu = lp if l_on and _bool(get('mitm_adv_loss_out'), True) else 0
    ld = lp if l_on and _bool(get('mitm_adv_loss_in'), True) else 0
    return du, dd, ju, jd, cu, cd, lu, ld


def gated_mitm_params(
    t_mono: float,
    t0: float,
    get: Get,
    row_t0: dict[str, float] | None = None,
) -> Tuple[int, int, int, int, float, float, int, int, Tuple[float, float, float, float]]:
    du, dd, ju, jd, cu, cd, lu, ld = base_mitm_params_from_get(get)
    gates = compute_timer_gates(t_mono, t0, get, row_t0)
    gd, gj, gc, gl = gates
    du2 = int(round(du * gd))
    dd2 = int(round(dd * gd))
    ju2 = int(round(ju * gj))
    jd2 = int(round(jd * gj))
    cu2 = round(cu * gc, 4)
    cd2 = round(cd * gc, 4)
    lu2 = int(round(lu * gl))
    ld2 = int(round(ld * gl))
    return du2, dd2, ju2, jd2, cu2, cd2, lu2, ld2, gates


def monotonic_now() -> float:
    return time.monotonic()


def sched_apply_tuple(
    du: int,
    dd: int,
    ju: int,
    jd: int,
    cu: float,
    cd: float,
    lu: int,
    ld: int,
    gates: Tuple[float, float, float, float],
) -> Tuple:
    """Comparable signature for Advanced Lag scheduler ticks (params + timer gates)."""
    return (
        int(du),
        int(dd),
        int(ju),
        int(jd),
        round(float(cu), 3),
        round(float(cd), 3),
        int(lu),
        int(ld),
        tuple(round(float(g), 4) for g in gates),
    )
