"""Locked Clumzy Mode packet profile (Mandy/hotspot: true + remote + Freeze)."""

FILTER = 'true'
# Clumzy divert.c: NetworkType == 1 is local NETWORK; anything else is NETWORK_FORWARD.
NETWORK_REMOTE = 2
LAG_MS = 100
DROP_CHANCE_PCT = 100.0
CYCLE_SETTLE_S = 0.08


def apply_freeze(engine, inbound: int = 1, outbound: int = 1, drop_pct: float | None = None) -> None:
    """Lag and drop at the locked Freeze values (optional direction / drop %)."""
    inn = 1 if inbound else 0
    out = 1 if outbound else 0
    chance = DROP_CHANCE_PCT if drop_pct is None else float(drop_pct)
    engine.lag(inn, out, LAG_MS)
    engine.drop(inn, out, chance)
    engine.enable('lag', True)
    engine.enable('drop', True)
    for name in (
        'disconnect',
        'bandwidth',
        'throttle',
        'duplicate',
        'ood',
        'tamper',
        'reset',
    ):
        engine.enable(name, False)
