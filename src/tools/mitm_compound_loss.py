"""
Compounded packet loss for Advanced Lag shaping.

When compound mode is on, a single survival probability is used:

    P(forward) = (1 - loss%/100) × (1 - overflow%/100 if over bandwidth cap else 1)

So 50% loss and 50% cap-overflow loss ≈ 25% delivery (multiplicative), not two
independent sequential rolls with the same semantics.

``overflow_loss_pct`` defaults to 100: over-cap packets always lose the cap factor
(×0 survival), matching legacy always-drop behavior while still compounding with
loss in one Bernoulli trial.
"""

from __future__ import annotations

import random


def survival_probability(
    loss_pct: int,
    *,
    cap_active: bool,
    cap_can_forward: bool,
    overflow_loss_pct: int = 100,
) -> float:
    """
    Combined survival in [0, 1].

    ``cap_active``: a bandwidth cap is configured (> 0 Mbps).
    ``cap_can_forward``: token bucket allowed this packet (under cap).
    """
    lp = max(0, min(100, int(loss_pct)))
    surv = 1.0 - (lp / 100.0)
    if cap_active and not cap_can_forward:
        op = max(0, min(100, int(overflow_loss_pct)))
        surv *= 1.0 - (op / 100.0)
    return max(0.0, min(1.0, surv))


def should_drop_compounded(
    loss_pct: int,
    *,
    cap_active: bool,
    cap_can_forward: bool,
    overflow_loss_pct: int = 100,
) -> bool:
    """True if the packet should be dropped (one compounded random draw)."""
    return random.random() >= survival_probability(
        loss_pct,
        cap_active=cap_active,
        cap_can_forward=cap_can_forward,
        overflow_loss_pct=overflow_loss_pct,
    )


def effective_delivery_pct(
    loss_pct: int,
    *,
    cap_active: bool,
    cap_over_cap: bool,
    overflow_loss_pct: int = 100,
) -> float:
    """Expected delivery % for UI hints (ignores delay)."""
    return 100.0 * survival_probability(
        loss_pct,
        cap_active=cap_active,
        cap_can_forward=not cap_over_cap,
        overflow_loss_pct=overflow_loss_pct,
    )
