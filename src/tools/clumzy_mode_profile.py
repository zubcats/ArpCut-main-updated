"""Locked Clumzy Mode packet profile (Mandy/hotspot: true + remote + Freeze)."""

FILTER = 'true'
# Clumzy divert.c: NetworkType == 1 is local NETWORK; anything else is NETWORK_FORWARD.
NETWORK_REMOTE = 2
LAG_MS = 100
DROP_CHANCE_PCT = 100.0
CYCLE_SETTLE_S = 0.08


def apply_freeze(engine) -> None:
    """Inbound+outbound lag and drop at the locked Freeze values."""
    engine.lag(1, 1, LAG_MS)
    engine.drop(1, 1, DROP_CHANCE_PCT)
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
