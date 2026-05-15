"""
Advanced Lag (MITM) per-impairment timer gates.

Each row can gate its contribution on a repeating schedule: impairment **on** for
``timer_lag_ms``, then **off** for ``timer_pause_ms``. When ``timer_repeat_forever`` is true,
that cycle repeats for the whole shaping session. When false, ``timer_runs`` is how many full
lag→pause cycles run before that row stays off (gate 0).
"""

from __future__ import annotations

import time
from typing import Any, Callable, Tuple

Get = Callable[[str], Any]


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
    pause_sec = max(0.0, pause_ms / 1000.0)
    period_sec = lag_sec + pause_sec
    if period_sec <= 0:
        return 1.0

    elapsed = t_mono - t0
    if elapsed < 0:
        return 1.0

    repeat_forever = _bool(get(f'{prefix}_timer_repeat_forever'), True)
    if not repeat_forever:
        runs = max(1, min(999, _int(get(f'{prefix}_timer_runs'), 1)))
        total_sec = runs * period_sec
        if elapsed >= total_sec:
            return 0.0

    pos = elapsed % period_sec
    if pos < lag_sec:
        return 1.0
    return 0.0


def compute_timer_gates(t_mono: float, t0: float, get: Get) -> Tuple[float, float, float, float]:
    return (
        gate_for_row(t_mono, t0, get, 'mitm_adv_delay'),
        gate_for_row(t_mono, t0, get, 'mitm_adv_jitter'),
        gate_for_row(t_mono, t0, get, 'mitm_adv_cap'),
        gate_for_row(t_mono, t0, get, 'mitm_adv_loss'),
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
) -> Tuple[int, int, int, int, float, float, int, int, Tuple[float, float, float, float]]:
    du, dd, ju, jd, cu, cd, lu, ld = base_mitm_params_from_get(get)
    gates = compute_timer_gates(t_mono, t0, get)
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
